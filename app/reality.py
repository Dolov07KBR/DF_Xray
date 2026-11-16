"""Сканер целей REALITY.

Проверяет домен или IP по TLS: версия протокола, ALPN, набор сертификата,
задержка и пригодность в качестве маскировки для REALITY.

Модуль не зависит от БД и не пишет на диск: на вход — список целей,
на выход — список словарей, которые можно отдать в API.
"""

from __future__ import annotations

import contextlib
import fnmatch
import ipaddress
import json
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

# Пресеты: популярные сайты, которые обычно хорошо подходят как цели REALITY.
DEFAULT_TARGETS: tuple[str, ...] = (
    "www.microsoft.com",
    "www.amazon.com",
    "aws.amazon.com",
    "www.cloudflare.com",
    "www.apple.com",
    "www.nvidia.com",
    "www.samsung.com",
    "www.intel.com",
)

MAX_TARGETS = 512
MAX_CIDR_HOSTS = 128
DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 5.0
DEFAULT_WORKERS = 16

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$",
    re.IGNORECASE,
)

STATUS_LABELS = {
    "ok": "Подходит",
    "weak": "Сомнительно",
    "fail": "Недоступно",
    "pending": "В очереди",
}

# --------------------------------------------------------------------------
# Цели
# --------------------------------------------------------------------------


@dataclass
class Target:
    host: str
    port: int = DEFAULT_PORT

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"


def _clean_token(token: str) -> tuple[str, int]:
    token = token.strip().strip(",;")
    port = DEFAULT_PORT
    if token.startswith("[") and "]" in token:  # [ipv6]:port
        host, _, rest = token[1:].partition("]")
        if rest.startswith(":"):
            port = _safe_port(rest[1:]) or DEFAULT_PORT
        return host, port
    match = re.match(r"^([^:]+):(\d{1,5})$", token)
    if match and not _looks_ipv6(token):
        return match.group(1), _safe_port(match.group(2)) or DEFAULT_PORT
    return token, port


def _looks_ipv6(value: str) -> bool:
    return value.count(":") >= 2


def _safe_port(value: Any) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return port if 1 <= port <= 65535 else 0


def _expand_token(token: str, port: int, limit: int) -> list[Target]:
    token = token.strip()
    if not token:
        return []
    if token.lower().startswith(("http://", "https://")):
        token = token.split("://", 1)[1]
    host, own_port = _clean_token(token)
    port = own_port if own_port != DEFAULT_PORT else port
    if not host:
        return []
    if "/" in host:  # CIDR
        try:
            network = ipaddress.ip_network(host, strict=False)
        except ValueError:
            return []
        hosts = [str(ip) for ip in network.hosts()] or [str(network.network_address)]
        return [Target(ip, port) for ip in hosts[:limit]]
    if "-" in host and not _looks_ipv6(host):
        start, _, end = host.partition("-")
        try:
            first = ipaddress.ip_address(start.strip())
            last = ipaddress.ip_address(end.strip())
        except ValueError:
            return [Target(host, port)]
        if first.version == last.version and int(last) >= int(first):
            total = min(int(last) - int(first) + 1, limit)
            return [
                Target(str(ipaddress.ip_address(int(first) + i)), port)
                for i in range(total)
            ]
    return [Target(host, port)]


def parse_targets(raw: str, port: int = DEFAULT_PORT, limit: int = MAX_TARGETS) -> list[Target]:
    """Разобрать строку с целями: домены, IP, CIDR и диапазоны через запятую/пробел."""
    text = (raw or "").replace("\n", ",").replace("\r", ",")
    tokens = [t for t in re.split(r"[\s,]+", text) if t.strip()]
    if not tokens:
        tokens = list(DEFAULT_TARGETS)
    result: list[Target] = []
    seen: set[tuple[str, int]] = set()
    for token in tokens:
        for target in _expand_token(token, port, limit):
            key = (target.host.lower(), target.port)
            if key in seen:
                continue
            seen.add(key)
            result.append(target)
            if len(result) >= limit:
                return result
    return result


def validate_target(host: str) -> str:
    host = (host or "").strip()
    if not host:
        raise ValueError("Пустая цель")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not DOMAIN_RE.match(host):
        raise ValueError(f"Некорректный домен: {host}")
    return host


# --------------------------------------------------------------------------
# Сертификат
# --------------------------------------------------------------------------


def _decode_certificate(der: bytes) -> dict[str, Any]:
    """Разобрать DER-сертификат средствами stdlib (без внешних зависимостей)."""
    if not der:
        return {}
    data = ""
    try:
        import ssl as _ssl

        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
            handle.write(_ssl.DER_cert_to_PEM_cert(der))
            path = handle.name
        try:
            data = _ssl._ssl._test_decode_cert(path)  # type: ignore[attr-defined]
        finally:
            import os

            os.unlink(path)
    except Exception:  # pragma: no cover - зависит от сборки Python
        data = {}
    if not isinstance(data, dict):
        data = {}
    subject = data.get("subject") or ()
    issuer = data.get("issuer") or ()
    sans = [value for kind, value in (data.get("subjectAltName") or ()) if kind in ("DNS", "IP Address")]
    return {
        "subject": _name_field(subject, "commonName"),
        "issuer": _name_field(issuer, "organizationName")
        or _name_field(issuer, "commonName"),
        "not_after": data.get("notAfter") or "",
        "san": sans,
        "serial": str(data.get("serialNumber") or ""),
    }


def _name_field(fields: Any, key: str) -> str:
    for item in fields or ():
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == key:
            return str(item[1])
        if isinstance(item, (list, tuple)):
            for child in item:
                if isinstance(child, (list, tuple)) and len(child) == 2 and child[0] == key:
                    return str(child[1])
    return ""


def certificate_matches(host: str, cert: dict[str, Any]) -> bool:
    names = [str(name) for name in (cert.get("san") or ())]
    if cert.get("subject"):
        names.append(str(cert["subject"]))
    host = host.lower()
    for name in names:
        pattern = name.lower().strip()
        if not pattern:
            continue
        if pattern.startswith("*."):
            base = pattern[2:]
            if host == base or host.endswith("." + base):
                return True
        elif fnmatch.fnmatch(host, pattern):
            return True
    return False


def _chain_summary(cert: dict[str, Any]) -> str:
    for name in cert.get("san") or ():
        name = str(name)
        if name:
            return name
    return str(cert.get("subject") or "")


# --------------------------------------------------------------------------
# OpenSSL-проба (обмен ключами и политика TLS)
# --------------------------------------------------------------------------

OPENSSL = shutil.which("openssl")
_OPENSSL_LOCK = threading.Lock()
_GROUPS_CACHE: dict[str, bool] = {}


def _openssl_supports_pq() -> bool:
    """Умеет ли локальный openssl в пост-квантовую группу X25519MLKEM768.

    Проверяем разбор опции: при старой версии openssl отвечает
    «cannot be set» ещё до попытки подключения.
    """
    if not OPENSSL:
        return False
    with _OPENSSL_LOCK:
        cached = _GROUPS_CACHE.get("pq")
        if cached is not None:
            return cached
        supported = False
        try:
            out = subprocess.run(
                [OPENSSL, "s_client", "-connect", "127.0.0.1:1",
                 "-groups", "X25519MLKEM768"],
                input="",
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            blob = (out.stdout or "") + (out.stderr or "")
            supported = "cannot be set" not in blob and "invalid group" not in blob.lower()
        except (OSError, subprocess.SubprocessError):
            supported = False
        _GROUPS_CACHE["pq"] = supported
        return supported


def _openssl_probe(host: str, port: int, timeout: float) -> dict[str, Any]:
    """Уточнить TLS-параметры через `openssl s_client -brief`."""
    if not OPENSSL:
        return {}
    args = [
        OPENSSL, "s_client", "-connect", f"{host}:{port}",
        "-servername", host, "-tls1_3", "-brief", "-alpn", "h2,http/1.1",
    ]
    try:
        out = subprocess.run(
            args,
            input="",
            capture_output=True,
            text=True,
            timeout=max(2.0, timeout),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    blob = (out.stdout or "") + (out.stderr or "")
    info: dict[str, Any] = {}
    for line in blob.splitlines():
        line = line.strip()
        if line.lower().startswith("negotiated tls"):
            info["group"] = line.split(":", 1)[-1].strip()
        elif line.lower().startswith("protocol version:"):
            info["protocol"] = line.split(":", 1)[-1].strip()
        elif line.lower().startswith("ciphersuite:"):
            info["cipher"] = line.split(":", 1)[-1].strip()
        elif line.lower().startswith("server temp key:"):
            info["group"] = line.split(":", 1)[-1].split(",")[0].strip()
        elif line.lower().startswith("alpn protocol:"):
            info["alpn"] = line.split(":", 1)[-1].strip()
    return info


def detect_pq(host: str, port: int, timeout: float = 5.0) -> bool | None:
    """Поддерживает ли цель пост-квантовый обмен ключами X25519MLKEM768."""
    if not _openssl_supports_pq():
        return None
    try:
        out = subprocess.run(
            [
                OPENSSL, "s_client", "-connect", f"{host}:{port}",
                "-servername", host, "-tls1_3",
                "-groups", "X25519MLKEM768", "-brief",
            ],
            input="",
            capture_output=True,
            text=True,
            timeout=max(2.0, timeout),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    blob = (out.stdout or "") + (out.stderr or "")
    if "Negotiated TLS1.3 group: X25519MLKEM768" in blob:
        return True
    if "X25519MLKEM768" in blob and "Verify return code" in blob:
        return True
    if "no suitable key share" in blob or "no shared cipher" in blob or "handshake failure" in blob:
        return False
    return None


# --------------------------------------------------------------------------
# Проба одной цели
# --------------------------------------------------------------------------


@dataclass
class Probe:
    target: str
    host: str
    port: int
    status: str = "fail"
    reason: str = ""
    tls: str = ""
    alpn: str = ""
    kex: str = ""
    cert: str = ""
    chain: str = ""
    latency_ms: int = 0
    issuer: str = ""
    not_after: str = ""
    cipher: str = ""
    pq: bool | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "reason": self.reason,
            "tls": self.tls,
            "alpn": self.alpn,
            "kex": self.kex,
            "cert": self.cert,
            "chain": self.chain,
            "latency_ms": self.latency_ms,
            "issuer": self.issuer,
            "not_after": self.not_after,
            "cipher": self.cipher,
            "pq": self.pq,
            "error": self.error,
        }


def probe_target(host: str, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT,
                 *, use_openssl: bool = True) -> Probe:
    """Проверить одну цель: рукопожатие, сертификат, ALPN, задержка."""
    result = Probe(target=f"{host}:{port}", host=host, port=port)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(NotImplementedError, ssl.SSLError):
        context.set_alpn_protocols(["h2", "http/1.1"])
    started = time.monotonic()
    sock = None
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            sock = context.wrap_socket(raw, server_hostname=host)
            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.tls = sock.version() or ""
            result.cipher = (sock.cipher() or ("", "", 0))[0]
            result.alpn = sock.selected_alpn_protocol() or ""
            der = sock.getpeercert(binary_form=True) or b""
        finally:
            try:
                if sock is not None:
                    sock.close()
                else:
                    raw.close()
            except OSError:
                pass
    except (socket.timeout, TimeoutError):
        result.error = "таймаут подключения"
        result.reason = "Сервер не ответил за отведённое время"
        return result
    except (ssl.SSLError, OSError, ValueError) as exc:
        result.error = str(exc) or exc.__class__.__name__
        result.reason = "TLS-рукопожатие не удалось"
        return result

    cert = _decode_certificate(der)
    result.cert = cert.get("subject", "")
    result.chain = _chain_summary(cert)
    result.issuer = cert.get("issuer", "")
    result.not_after = cert.get("not_after", "")
    if use_openssl:
        info = _openssl_probe(host, port, timeout)
        result.kex = info.get("group", "")
        if not result.tls and info.get("protocol"):
            result.tls = info["protocol"]
        if not result.alpn and info.get("alpn"):
            result.alpn = info["alpn"]
        result.pq = detect_pq(host, port, timeout)
    if not result.kex:
        result.kex = "—"

    matches = certificate_matches(host, cert) if (cert.get("san") or cert.get("subject")) else True
    reasons: list[str] = []
    if result.tls != "TLSv1.3":
        reasons.append(f"протокол {result.tls or 'неизвестен'} вместо TLS 1.3")
    if result.alpn != "h2":
        reasons.append("нет ALPN h2")
    if not matches:
        reasons.append("сертификат не совпадает с целью")
    if result.latency_ms > 1500:
        reasons.append("высокая задержка")
    if reasons:
        result.status = "weak"
        result.reason = "; ".join(reasons)
    else:
        result.status = "ok"
        result.reason = "TLS 1.3 + h2, сертификат валиден для цели"
    return result


# --------------------------------------------------------------------------
# Пакетный скан (в фоне)
# --------------------------------------------------------------------------


@dataclass
class ScanJob:
    id: str
    targets: list[Target]
    status: str = "running"
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancelled: bool = False
    error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "status": self.status,
                "total": len(self.targets),
                "done": len(self.results),
                "results": list(self.results),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "cancelled": self.cancelled,
            }


class ScanManager:
    """Фоновые задания сканирования с ограничением на количество."""

    def __init__(self, max_jobs: int = 16, retention_seconds: float = 3600.0) -> None:
        self.jobs: dict[str, ScanJob] = {}
        self.max_jobs = max_jobs
        self.retention = retention_seconds
        self._lock = threading.Lock()

    def start(
        self,
        raw_targets: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        workers: int = DEFAULT_WORKERS,
        limit: int = MAX_TARGETS,
    ) -> ScanJob:
        targets = parse_targets(raw_targets, port=port, limit=min(limit, MAX_TARGETS))
        if not targets:
            raise ValueError("Не удалось разобрать цели")
        job = ScanJob(id=uuid.uuid4().hex[:12], targets=targets)
        with self._lock:
            self._prune()
            self.jobs[job.id] = job
        thread = threading.Thread(
            target=self._run,
            args=(job, timeout, max(1, min(workers, 32))),
            name=f"reality-scan-{job.id}",
            daemon=True,
        )
        job.thread = thread
        thread.start()
        return job

    def _prune(self) -> None:
        if len(self.jobs) < self.max_jobs:
            return
        finished = sorted(
            (job for job in self.jobs.values() if job.status != "running"),
            key=lambda job: job.started_at,
        )
        for job in finished[: max(1, len(self.jobs) - self.max_jobs + 1)]:
            self.jobs.pop(job.id, None)

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job.cancelled = True
        return True

    def _run(self, job: ScanJob, timeout: float, workers: int) -> None:
        def work(target: Target) -> dict[str, Any]:
            if job.cancelled:
                return {}
            try:
                return probe_target(target.host, target.port, timeout).to_dict()
            except Exception as exc:  # pragma: no cover - защитный контур
                probe = Probe(target=target.label, host=target.host, port=target.port)
                probe.error = str(exc)
                probe.reason = "Внутренняя ошибка пробы"
                return probe.to_dict()

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(work, target) for target in job.targets]
                for future in futures:
                    if job.cancelled:
                        break
                    try:
                        item = future.result(timeout=timeout * 4)
                    except Exception as exc:  # pragma: no cover
                        item = {
                            "target": "—",
                            "status": "fail",
                            "status_label": STATUS_LABELS["fail"],
                            "error": str(exc),
                            "reason": "Проба прервана",
                        }
                    if item:
                        with job.lock:
                            job.results.append(item)
        except Exception as exc:  # pragma: no cover
            job.error = str(exc)
        finally:
            with job.lock:
                job.status = "cancelled" if job.cancelled else "done"
                job.finished_at = time.time()

    def stop(self) -> None:
        for job in list(self.jobs.values()):
            job.cancelled = True


MANAGER = ScanManager()


def scan_once(targets: str, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT,
              workers: int = DEFAULT_WORKERS) -> list[dict[str, Any]]:
    """Синхронный скан — используется в тестах и CLI."""
    job = MANAGER.start(targets, port=port, timeout=timeout, workers=workers)
    if job.thread is not None:
        job.thread.join(timeout=timeout * max(2, len(job.targets)))
    return job.snapshot()["results"]


def dumps(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, indent=2)
