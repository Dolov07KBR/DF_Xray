"""Проверка новых версий панели и обновление из интерфейса.

Проверка ходит в GitHub API и кэшируется в настройках. Обновление
выполняется внешней командой (установщик или docker compose), если
панель установлена с поддержкой самообновления; иначе возвращаются
инструкции для сервера.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config, db

REPO_DEFAULT = "Dolov07KBR/DF_Xray"
CACHE_TTL = 6 * 3600
MAX_LOG = 20000

SELF_TARGET = os.environ.get("DFX_SELF_DIR", "/app")
SELF_MARKER = "DFX_SELF_UPDATE"
# Что копируем при самообновлении: код, статика, установщик и документация.
SELF_PATHS = (
    "app", "static", "node", "bin", "docs", "install.sh",
    "README.md", "LICENSE", "pyproject.toml", "Makefile",
    "docker-compose.yml", "docker-compose.selfupdate.yml", "Dockerfile", ".env.example",
)

_STATE: dict[str, Any] = {
    "running": False,
    "ok": None,
    "log": "",
    "command": "",
    "started_at": 0.0,
    "finished_at": 0.0,
}
_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------


def repo() -> str:
    return (os.environ.get("DFX_UPDATE_REPO") or REPO_DEFAULT).strip()


def current_version() -> str:
    return config.APP_VERSION


def _version_tuple(value: str) -> tuple[int, ...]:
    cleaned = (value or "").strip().lstrip("vV")
    parts = re.split(r"[.\-+]", cleaned)
    numbers: list[int] = []
    for part in parts:
        if part.isdigit():
            numbers.append(int(part))
        else:
            break
    return tuple(numbers)


def is_newer(latest: str, current: str) -> bool:
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    if latest_tuple and current_tuple:
        length = max(len(latest_tuple), len(current_tuple))
        return latest_tuple + (0,) * (length - len(latest_tuple)) > current_tuple + (
            0,
        ) * (length - len(current_tuple))
    return bool(latest) and latest.strip() != current.strip()


def _get_json(url: str, timeout: float = 8.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"DF_Xray-Panel/{config.APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8"))


# --------------------------------------------------------------------------
# Проверка версии
# --------------------------------------------------------------------------


def _fetch_latest() -> dict[str, Any]:
    repo_name = repo()
    try:
        data = _get_json(f"https://api.github.com/repos/{repo_name}/releases/latest")
        if isinstance(data, dict) and data.get("tag_name"):
            return {
                "latest": str(data["tag_name"]),
                "notes": str(data.get("body") or "")[:6000],
                "url": str(data.get("html_url") or ""),
                "published_at": str(data.get("published_at") or ""),
                "source": "release",
            }
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 403):
            raise
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise

    tags = _get_json(f"https://api.github.com/repos/{repo_name}/tags?per_page=20")
    if isinstance(tags, list) and tags:
        names = [str(tag.get("name") or "") for tag in tags if isinstance(tag, dict)]
        versions = sorted(
            (name for name in names if _version_tuple(name)),
            key=_version_tuple,
            reverse=True,
        )
        latest = versions[0] if versions else names[0]
        return {
            "latest": latest,
            "notes": "",
            "url": f"https://github.com/{repo_name}/releases/tag/{latest}",
            "published_at": "",
            "source": "tag",
        }

    commits = _get_json(f"https://api.github.com/repos/{repo_name}/commits?per_page=1")
    if isinstance(commits, list) and commits:
        commit = commits[0]
        sha = str(commit.get("sha") or "")[:7]
        return {
            "latest": current_version(),
            "notes": "",
            "url": f"https://github.com/{repo_name}/commit/{sha}",
            "published_at": str((commit.get("commit") or {}).get("committer", {}).get("date") or ""),
            "source": "commit",
            "commit": sha,
        }
    raise RuntimeError("В репозитории нет релизов и тегов")


def cached() -> dict[str, Any]:
    settings = db.get_settings()
    return {
        "current": current_version(),
        "latest": settings.get("update_latest", ""),
        "notes": settings.get("update_notes", ""),
        "url": settings.get("update_url", ""),
        "checked_at": settings.get("update_check_ts", ""),
        "repo": repo(),
    }


def check(force: bool = False) -> dict[str, Any]:
    """Проверить обновления. Результат кэшируется на 6 часов."""
    settings = db.get_settings()
    stamp = settings.get("update_check_ts") or ""
    try:
        stamp_ts = float(stamp)
    except ValueError:
        stamp_ts = 0.0
    fresh = (time.time() - stamp_ts) < CACHE_TTL if stamp_ts else False
    if fresh and not force:
        payload = cached()
        payload.update(
            {
                "update_available": is_newer(payload["latest"], payload["current"]),
                "cached": True,
                "source": "cache",
            }
        )
        return payload

    result: dict[str, Any] = {
        "current": current_version(),
        "latest": "",
        "notes": "",
        "url": "",
        "checked_at": "",
        "repo": repo(),
        "update_available": False,
        "cached": False,
        "error": "",
        "source": "",
        "commit": "",
    }
    try:
        latest = _fetch_latest()
    except Exception as exc:  # сеть недоступна, репозиторий приватный и т.п.
        result["error"] = f"Не удалось проверить обновления: {exc}"
        result["checked_at"] = stamp
        return result

    result.update(latest)
    result["update_available"] = is_newer(latest["latest"], result["current"])
    result["checked_at"] = str(int(time.time()))
    db.update_settings(
        {
            "update_check_ts": result["checked_at"],
            "update_latest": result["latest"],
            "update_notes": result["notes"],
            "update_url": result["url"],
        }
    )
    return result


# --------------------------------------------------------------------------
# Установка обновления
# --------------------------------------------------------------------------


def install_dir() -> pathlib.Path:
    """Каталог установки: настройка панели, переменная окружения или /opt/dfxray."""
    raw = ""
    try:
        raw = str(db.get_setting("install_dir", "") or "")
    except Exception:  # база может быть ещё не инициализирована (CLI, тесты)
        raw = ""
    raw = (raw or os.environ.get("DFX_HOME", "") or "/opt/dfxray").strip()
    return pathlib.Path(raw)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        probe = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def code_dir() -> pathlib.Path:
    """Каталог, из которого запущен код панели (родитель пакета app)."""
    return pathlib.Path(__file__).resolve().parent.parent


def _writable(path: pathlib.Path) -> bool:
    marker = path / "app"
    if not marker.is_dir():
        return False
    try:
        probe = path / ".dfx-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return bool(os.access(path, os.W_OK))


def in_container() -> bool:
    return pathlib.Path("/.dockerenv").exists() or pathlib.Path("/run/.containerenv").exists()


def supervised() -> bool:
    """Перезапустит ли нас супервизор (Docker, systemd) после выхода из процесса."""
    if os.environ.get("DFX_SUPERVISED") == "1":
        return True
    return in_container() or bool(os.environ.get("INVOCATION_ID"))


def self_target() -> pathlib.Path:
    """Куда писать обновление: смонтированный каталог установки или свой код."""
    if os.environ.get(SELF_MARKER) == "1":
        return pathlib.Path(SELF_TARGET)
    return code_dir()


def self_capable() -> bool:
    """Может ли панель обновить свой код сама (без docker и установщика)."""
    return _writable(self_target())


CODE_PATHS = "app static node bin docs install.sh docker-compose.yml docker-compose.selfupdate.yml Dockerfile pyproject.toml Makefile README.md LICENSE"


def manual_command() -> str:
    """Команда, которую пользователь может скопировать и выполнить на сервере."""
    target = install_dir()
    marker = os.environ.get(SELF_MARKER) == "1"
    if marker:
        # Права на смонтированный код: панель в контейнере работает под uid 1000.
        return (
            f"cd {target} && sudo chown -R 1000:1000 {CODE_PATHS} && "
            "sudo docker compose -f docker-compose.yml -f docker-compose.selfupdate.yml "
            "up -d panel"
        )
    if (target / "docker-compose.yml").is_file():
        return f"cd {target} && sudo docker compose pull && sudo docker compose up -d"
    return f"cd {target} && sudo ./install.sh --yes"


def capability() -> dict[str, Any]:
    """Что панель умеет делать с обновлением и что показать пользователю."""
    target = install_dir()
    instructions = manual_command()
    if self_capable():
        where = self_target()
        return {
            "mode": "self",
            "label": "Самообновление",
            "command": f"python -m app self-update --target {where}",
            "hint": f"Код панели обновляется на месте: {where}",
            "instructions": instructions,
        }
    try:
        stored = str(db.get_setting("update_command", "") or "")
    except Exception:
        stored = ""
    custom = (stored or os.environ.get("DFX_UPDATE_COMMAND", "")).strip()
    if custom:
        return {
            "mode": "command",
            "label": "Команда обновления",
            "command": custom,
            "hint": "Задана в настройках панели",
            "instructions": instructions,
        }
    script = target / "install.sh"
    if script.is_file() and shutil.which("bash") and os.geteuid() == 0:
        return {
            "mode": "installer",
            "label": "Установщик",
            "command": f"bash {script} --dir {target} --yes",
            "hint": f"Найден {script}",
            "instructions": instructions,
        }
    if _docker_available() and (target / "docker-compose.yml").is_file():
        return {
            "mode": "compose",
            "label": "Docker Compose",
            "command": (
                f"docker compose --project-directory {target} -f {target}/docker-compose.yml "
                "build panel && "
                f"docker compose --project-directory {target} -f {target}/docker-compose.yml "
                "up -d panel"
            ),
            "hint": "Пересборка контейнера из каталога установки",
            "instructions": instructions,
        }
    # Объясняем причину, а не просто «недоступно».
    if os.environ.get(SELF_MARKER) == "1":
        reason = (
            f"Код смонтирован из {target}, но контейнер не может туда писать: "
            "файлы принадлежат root, а панель работает под uid 1000. "
            "Один раз выполните команду ниже — дальше кнопка заработает"
        )
    elif in_container():
        reason = (
            "Панель работает в контейнере без монтирования кода, поэтому обновить "
            "файлы изнутри нельзя. Обновите контейнер на сервере"
        )
    else:
        reason = "Каталог панели недоступен для записи"
    return {
        "mode": "manual",
        "label": "Вручную на сервере",
        "command": "",
        "hint": reason,
        "reason": reason,
        "instructions": instructions,
    }


def _download(url: str, destination: str, timeout: float = 120.0) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"DF_Xray-Panel/{config.APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(destination, "wb") as handle:
        shutil.copyfileobj(response, handle)


def _safe_members(archive: tarfile.TarFile, prefix: str) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        name = member.name
        if prefix and name.startswith(prefix):
            name = name[len(prefix):]
        else:
            continue
        if not name or name.startswith(("/", "..")) or ".." in pathlib.PurePosixPath(name).parts:
            continue
        top = pathlib.PurePosixPath(name).parts[0]
        if top not in SELF_PATHS:
            continue
        member.name = name
        members.append(member)
    return members


def self_update(ref: str = "main", target: str | None = None) -> dict[str, Any]:
    """Скачать свежие исходники и заменить код панели на месте."""
    destination = pathlib.Path(target or SELF_TARGET)
    if not destination.is_dir():
        raise RuntimeError(f"Каталог панели не найден: {destination}")
    repo_name = repo()
    tmp = tempfile.mkdtemp(prefix="dfxray-update-")
    archive_path = os.path.join(tmp, "src.tar.gz")
    try:
        downloaded = False
        for candidate in (
            f"https://codeload.github.com/{repo_name}/tar.gz/refs/heads/{ref}",
            f"https://codeload.github.com/{repo_name}/tar.gz/refs/tags/{ref}",
            f"https://codeload.github.com/{repo_name}/tar.gz/{ref}",
        ):
            try:
                _download(candidate, archive_path)
                downloaded = True
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
        if not downloaded:
            raise RuntimeError("Не удалось скачать исходники с GitHub")
        copied = 0
        with tarfile.open(archive_path) as archive:
            names = archive.getnames()
            prefix = f"{names[0].split('/')[0]}/" if names else ""
            members = _safe_members(archive, prefix)
            if not members:
                raise RuntimeError("В архиве нет файлов панели")
            for member in members:
                try:
                    archive.extract(member, tmp, filter="data")
                except TypeError:  # Python < 3.11.4
                    archive.extract(member, tmp)
                source = pathlib.Path(tmp) / member.name
                if member.isdir():
                    (destination / member.name).mkdir(parents=True, exist_ok=True)
                    continue
                target_path = destination / member.name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_path)
                copied += 1
        return {"ok": True, "files": copied, "ref": ref, "target": str(destination)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restart_soon(delay: float = 2.0) -> None:
    """Перезапустить процесс панели: контейнер поднимется заново по restart policy."""

    def _exit() -> None:
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_exit, name="dfxray-restart", daemon=True).start()


def _append_log(text: str) -> None:
    with _LOCK:
        _STATE["log"] = (_STATE["log"] + text)[-MAX_LOG:]


def _run_native(target: pathlib.Path) -> None:
    """Обновить код панели на месте (без docker и внешних команд)."""
    with _LOCK:
        _STATE.update(
            {
                "running": True,
                "ok": None,
                "log": f"$ python -m app self-update --target {target}\n",
                "command": f"self-update --target {target}",
                "started_at": time.time(),
                "finished_at": 0.0,
            }
        )
    try:
        _append_log("Скачиваю свежие исходники с GitHub…\n")
        result = self_update(target=str(target))
        _append_log(f"Файлов обновлено: {result.get('files', 0)} (ref {result.get('ref')})\n")
        with _LOCK:
            _STATE["ok"] = True
            _STATE["finished_at"] = time.time()
        if supervised():
            _append_log("Перезапускаю панель…\n")
            restart_soon(2.5)
        else:
            _append_log("Готово. Перезапустите панель: systemctl restart dfxray-panel\n")
    except Exception as exc:
        _append_log(f"[ошибка] {exc}\n")
        with _LOCK:
            _STATE["ok"] = False
            _STATE["finished_at"] = time.time()
    finally:
        with _LOCK:
            _STATE["running"] = False


def _run(command: str) -> None:
    with _LOCK:
        _STATE.update(
            {
                "running": True,
                "ok": None,
                "log": f"$ {command}\n",
                "command": command,
                "started_at": time.time(),
                "finished_at": 0.0,
            }
        )
    try:
        process = subprocess.Popen(
            shlex.split(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(install_dir()) if install_dir().is_dir() else None,
        )
        assert process.stdout is not None
        for line in process.stdout:
            _append_log(line)
        code = process.wait(timeout=1800)
        with _LOCK:
            _STATE["ok"] = code == 0
            _STATE["finished_at"] = time.time()
            _STATE["log"] = (_STATE["log"] + f"\n[код возврата {code}]\n")[-MAX_LOG:]
        if code == 0 and self_capable():
            _append_log("Код обновлён, перезапускаю панель…\n")
            restart_soon(2.5)
    except Exception as exc:
        with _LOCK:
            _STATE["ok"] = False
            _STATE["finished_at"] = time.time()
            _STATE["log"] = (_STATE["log"] + f"\n[ошибка] {exc}\n")[-MAX_LOG:]
    finally:
        with _LOCK:
            _STATE["running"] = False


def start_update() -> dict[str, Any]:
    with _LOCK:
        if _STATE["running"]:
            raise RuntimeError("Обновление уже выполняется")
    info = capability()
    if info["mode"] == "manual" or (not info["command"] and info["mode"] != "self"):
        hint = info.get("reason") or info.get("hint") or "Автообновление недоступно"
        raise RuntimeError(f"{hint}. Команда на сервере: {info.get('instructions', '')}".strip())
    if info["mode"] == "self":
        thread = threading.Thread(
            target=_run_native, args=(self_target(),), name="dfxray-update", daemon=True
        )
        thread.start()
        return {"started": True, "command": info["command"], "mode": "self"}
    thread = threading.Thread(target=_run, args=(info["command"],), name="dfxray-update", daemon=True)
    thread.start()
    return {"started": True, "command": info["command"], "mode": info["mode"]}


def status() -> dict[str, Any]:
    with _LOCK:
        snapshot = dict(_STATE)
    snapshot["capability"] = capability()
    snapshot["current"] = current_version()
    return snapshot
