"""Мини-фреймворк поверх http.server: роутинг, JSON, cookie, статика."""

from __future__ import annotations

import contextlib
import json
import mimetypes
import re
import sys
import traceback
import urllib.parse
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import auth, config, db
from .utils import iso

MAX_BODY = 2 * 1024 * 1024


# --------------------------------------------------------------------------
# Запрос / ответ
# --------------------------------------------------------------------------


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    cookies: dict[str, str]
    body: bytes
    remote: str
    scheme: str
    host: str
    params: dict[str, str] = field(default_factory=dict)
    admin: dict[str, Any] | None = None
    _json: Any = None

    # --- утилиты ---
    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    def q(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return values[0] if values else default

    def q_int(self, name: str, default: int = 0) -> int:
        try:
            return int(self.q(name, str(default)) or default)
        except ValueError:
            return default

    def json(self) -> dict[str, Any]:
        if self._json is None:
            if not self.body:
                self._json = {}
            else:
                try:
                    parsed = json.loads(self.body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ApiError(400, "Некорректный JSON в запросе") from exc
                if not isinstance(parsed, dict):
                    raise ApiError(400, "Ожидался JSON-объект")
                self._json = parsed
        return self._json

    @property
    def ip(self) -> str:
        if config.TRUST_PROXY:
            forwarded = self.header("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.remote

    def base_url(self) -> str:
        configured = (db.get_setting("public_base_url") or "").strip()
        if configured:
            return configured.rstrip("/")
        if config.BASE_URL:
            return config.BASE_URL
        host = self.header("x-forwarded-host") or self.host
        scheme = self.header("x-forwarded-proto") or self.scheme
        return f"{scheme}://{host}".rstrip("/")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Response:
    def __init__(
        self,
        body: bytes | str = b"",
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)

    def set_cookie(
        self,
        name: str,
        value: str,
        *,
        max_age: int | None = None,
        http_only: bool = True,
        secure: bool = False,
        same_site: str = "Lax",
        path: str = "/",
    ) -> Response:
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")
        self.headers.setdefault("Set-Cookie", "")
        self.headers["Set-Cookie"] = "; ".join(parts)
        return self


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, default=str),
        status=status,
        content_type="application/json; charset=utf-8",
        headers=headers,
    )


def error_response(status: int, message: str) -> Response:
    return json_response({"error": message}, status=status)


def html_response(body: str, status: int = 200) -> Response:
    return Response(body, status=status, content_type="text/html; charset=utf-8")


def redirect(location_: str, status: int = 302) -> Response:
    return Response(b"", status=status, headers={"Location": location_})


# --------------------------------------------------------------------------
# Роутинг
# --------------------------------------------------------------------------


@dataclass
class Route:
    method: str
    regex: re.Pattern[str]
    handler: Callable[[Request], Response]
    auth_required: bool


ROUTES: list[Route] = []


def route(method: str, pattern: str, auth_required: bool = True):
    compiled = re.compile("^" + pattern + "$")

    def decorator(handler: Callable[[Request], Response]):
        ROUTES.append(
            Route(method.upper(), compiled, handler, auth_required)
        )
        return handler

    return decorator


def get(pattern: str, auth_required: bool = True):
    return route("GET", pattern, auth_required)


def post(pattern: str, auth_required: bool = True):
    return route("POST", pattern, auth_required)


def patch(pattern: str, auth_required: bool = True):
    return route("PATCH", pattern, auth_required)


def delete(pattern: str, auth_required: bool = True):
    return route("DELETE", pattern, auth_required)


def dispatch(req: Request) -> Response:
    allowed: set[str] = set()
    for item in ROUTES:
        match = item.regex.match(req.path)
        if not match:
            continue
        allowed.add(item.method)
        if item.method != req.method:
            continue
        req.params = {k: v for k, v in match.groupdict().items()}
        if item.auth_required:
            admin = auth.resolve_session(req.cookies.get(config.SESSION_COOKIE))
            if admin is None:
                raise ApiError(401, "Требуется авторизация")
            req.admin = admin
            # Простейшая CSRF-защита: SPA всегда отправляет этот заголовок.
            if req.method not in ("GET", "HEAD") and req.header("x-requested-with") != "DF_Xray":
                raise ApiError(403, "Отсутствует заголовок X-Requested-With")
        return item.handler(req)
    if allowed:
        raise ApiError(405, "Метод не поддерживается")
    raise ApiError(404, "Не найдено")


# --------------------------------------------------------------------------
# Статика
# --------------------------------------------------------------------------

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}


def serve_static(rel_path: str) -> Response:
    rel_path = rel_path.lstrip("/")
    candidate = (config.STATIC_DIR / rel_path).resolve()
    static_root = config.STATIC_DIR.resolve()
    if not str(candidate).startswith(str(static_root)) or not candidate.is_file():
        raise ApiError(404, "Файл не найден")
    ext = candidate.suffix.lower()
    content_type = MIME_TYPES.get(ext) or mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
    stat = candidate.stat()
    etag = f'W/"{int(stat.st_mtime)}-{stat.st_size}"'
    body = candidate.read_bytes()
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=300" if ext not in (".html",) else "no-cache",
    }
    return Response(body, content_type=content_type, headers=headers)


# --------------------------------------------------------------------------
# HTTP-обработчик
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = f"DFXray/{config.APP_VERSION}"
    protocol_version = "HTTP/1.1"

    # --- логирование ---
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            f"[{iso()}] {self.address_string()} {fmt % args}\n"
        )

    def _build_request(self) -> Request:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        headers = {k.lower(): v for k, v in self.headers.items()}
        cookie = SimpleCookie()
        if self.headers.get("Cookie"):
            with contextlib.suppress(Exception):
                cookie.load(self.headers["Cookie"])
        cookies = {k: v.value for k, v in cookie.items()}
        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Слишком большой запрос")
        body = self.rfile.read(length) if length else b""
        scheme = headers.get("x-forwarded-proto", "http").split(",")[0].strip()
        host = headers.get("x-forwarded-host") or headers.get("host", "localhost")
        return Request(
            method=self.command.upper(),
            path=urllib.parse.unquote(parsed.path or "/"),
            query=query,
            headers=headers,
            cookies=cookies,
            body=body,
            remote=self.client_address[0],
            scheme=scheme,
            host=host,
        )

    def _write(self, response: Response) -> None:
        body = response.body
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; font-src 'self' data:; frame-ancestors *; base-uri 'self'",
        )
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle(self) -> None:
        import app.api
        import app.pages  # noqa: F401

        try:
            request = self._build_request()
            response = dispatch(request)
            self._write(response)
        except ApiError as exc:
            is_json = request.path.startswith("/api/") if "request" in locals() else True
            if is_json:
                self._write(error_response(exc.status, exc.message))
            else:
                self._write(html_response(
                    f"<h1>{exc.status}</h1><p>{exc.message}</p>", status=exc.status
                ))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            sys.stderr.write(traceback.format_exc())
            self._write(error_response(500, "Внутренняя ошибка панели"))

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()


class PanelHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve() -> None:
    config.ensure_dirs()
    db.init()
    import app.api
    import app.pages  # noqa: F401

    server = PanelHTTPServer((config.HOST, config.PORT), Handler)
    print(
        f"[dfxray] {config.APP_NAME} v{config.APP_VERSION} слушает "
        f"http://{config.HOST}:{config.PORT} (данные: {config.DB_PATH})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dfxray] Остановлено", flush=True)
    finally:
        server.server_close()
