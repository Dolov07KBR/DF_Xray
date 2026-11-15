#!/usr/bin/env python3
"""DF_Xray Node Agent — связывает сервер Xray с панелью.

Агент работает по pull-модели: забирает у панели готовый config.json,
проверяет его через `xray -test`, перезапускает Xray при изменениях и
отдаёт обратно статистику трафика по пользователям.

Зависимости: только стандартная библиотека Python 3.9+ и бинарник xray.

Переменные окружения:
  DFX_PANEL_URL    адрес панели (http://panel:8000 или https://panel.example.com)
  DFX_NODE_TOKEN   токен ноды (панель → Ноды → Конфиг)
  DFX_XRAY_BIN     путь к бинарнику xray (по умолчанию /usr/local/bin/xray)
  DFX_CONFIG_PATH  путь к config.json (по умолчанию /etc/xray/config.json)
  DFX_POLL         период опроса в секундах (по умолчанию из ответа панели)
  DFX_DRY_RUN     1 — не запускать xray (для отладки)
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PANEL_URL = os.environ.get("DFX_PANEL_URL", "").rstrip("/")
NODE_TOKEN = os.environ.get("DFX_NODE_TOKEN", "").strip()
XRAY_BIN = os.environ.get("DFX_XRAY_BIN", shutil.which("xray") or "/usr/local/bin/xray")
CONFIG_PATH = os.environ.get("DFX_CONFIG_PATH", "/etc/xray/config.json")
POLL = int(os.environ.get("DFX_POLL", "30"))
DRY_RUN = os.environ.get("DFX_DRY_RUN", "0") in ("1", "true", "yes")
STATS_API = os.environ.get("DFX_STATS_API", "127.0.0.1:10085")
LOG_LEVEL = os.environ.get("DFX_LOG_LEVEL", "info").lower()

STOP = False

AGENT_VERSION = "1.2.0"
APPLIED_REVISION = ""
LAST_ERROR = ""


def log(message: str, level: str = "info") -> None:
    order = {"debug": 10, "info": 20, "warn": 30, "error": 40}
    if order.get(level, 20) < order.get(LOG_LEVEL, 20):
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[{stamp}] {level.upper():5} {message}\n")
    sys.stderr.flush()


def _request(method: str, url: str, payload: dict | None = None, timeout: float = 20) -> dict:
    data = None
    headers = {"X-Node-Token": NODE_TOKEN, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def fetch_config() -> dict:
    query = urllib.parse.urlencode({"token": NODE_TOKEN})
    return _request("GET", f"{PANEL_URL}/api/agent/config?{query}")


def report(payload: dict) -> dict:
    return _request("POST", f"{PANEL_URL}/api/agent/report", payload)


def heartbeat(payload: dict) -> dict:
    return _request("POST", f"{PANEL_URL}/api/agent/heartbeat", payload)


# --------------------------------------------------------------------------
# Метрики сервера
# --------------------------------------------------------------------------


def system_metrics() -> dict:
    """Данные о сервере для панели: uptime, load average, память."""
    metrics = {"agent_version": AGENT_VERSION, "xray_running": False,
               "uptime": 0, "load1": 0.0, "memory": {"used": 0, "total": 0}}
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            metrics["uptime"] = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        metrics["uptime"] = int(time.time())
    try:
        metrics["load1"] = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        metrics["load1"] = 0.0
    try:
        meminfo = {}
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                meminfo[key.strip()] = int(rest.strip().split()[0]) * 1024
        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        metrics["memory"] = {"used": max(0, total - available), "total": total}
    except (OSError, ValueError, IndexError):
        pass
    if DRY_RUN:
        metrics["xray_running"] = True
    else:
        metrics["xray_running"] = xray.is_running()
    metrics["revision"] = APPLIED_REVISION
    metrics["last_error"] = LAST_ERROR
    return metrics


# --------------------------------------------------------------------------
# Xray
# --------------------------------------------------------------------------


class XrayProcess:
    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.backoff = 1.0
        self.version = ""

    def binary_available(self) -> bool:
        return os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK)

    def detect_version(self) -> str:
        if self.version:
            return self.version
        if not self.binary_available():
            return ""
        try:
            output = subprocess.run(
                [XRAY_BIN, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            first = (output.stdout or output.stderr).strip().splitlines()
            if first:
                match = re.search(r"Xray\s+([\d.]+)", first[0])
                self.version = f"Xray {match.group(1)}" if match else first[0][:40]
        except (OSError, subprocess.SubprocessError):
            self.version = ""
        return self.version

    def test_config(self, path: str) -> tuple[bool, str]:
        if DRY_RUN or not self.binary_available():
            return True, "dry-run"
        try:
            result = subprocess.run(
                [XRAY_BIN, "-test", "-config", path],
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()[-500:]

    def start(self) -> None:
        if DRY_RUN:
            log("dry-run: xray не запускается", "warn")
            return
        if not self.binary_available():
            log(f"бинарник xray не найден: {XRAY_BIN}", "error")
            return
        if self.is_running():
            return
        log(f"запускаю {XRAY_BIN} -config {CONFIG_PATH}")
        try:
            self.process = subprocess.Popen(
                [XRAY_BIN, "run", "-config", CONFIG_PATH],
                stdout=sys.stderr,
                stderr=sys.stderr,
            )
        except OSError as exc:
            log(f"не удалось запустить xray: {exc}", "error")
            self.process = None

    def stop(self, timeout: float = 8.0) -> None:
        if not self.process:
            return
        log("останавливаю xray")
        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
        except OSError:
            pass
        self.process = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def ensure_running(self) -> None:
        if DRY_RUN:
            return
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            log(f"xray завершился с кодом {code}, перезапуск через {self.backoff:.0f} с", "warn")
            self.process = None
            time.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, 60)
            self.start()
        elif self.process is None:
            self.start()
        else:
            self.backoff = 1.0


def write_config(config: dict, path: str) -> bool:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    body = json.dumps(config, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(prefix=".dfxray-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body + "\n")
        os.chmod(tmp_path, 0o640)
        os.replace(tmp_path, path)
    except OSError as exc:
        log(f"не удалось записать конфиг: {exc}", "error")
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        return False
    return True


# --------------------------------------------------------------------------
# Статистика
# --------------------------------------------------------------------------

STAT_LINE = re.compile(r"stat:\s*(\S+)\s+value:\s*(\d+)")


def query_stats() -> dict[str, dict[str, int]]:
    """Снять и сбросить счётчики Xray, вернуть {email: {up, down}}."""
    if DRY_RUN or not os.path.isfile(XRAY_BIN):
        return {}
    try:
        result = subprocess.run(
            [XRAY_BIN, "api", "statsquery", f"--server={STATS_API}", "-reset"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"statsquery: {exc}", "warn")
        return {}
    output = (result.stdout or "").strip()
    if not output:
        if result.returncode not in (0,):
            log(f"statsquery вернул код {result.returncode}: {result.stderr.strip()[:200]}", "debug")
        return {}

    users: dict[str, dict[str, int]] = {}
    entries: list[tuple[str, int]] = []

    if output.startswith(("{", "[")):
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for item in payload.get("stat", []) or []:
                entries.append((item.get("name", ""), int(item.get("value", 0) or 0)))
        elif isinstance(payload, list):
            for item in payload:
                entries.append((item.get("name", ""), int(item.get("value", 0) or 0)))
    if not entries:
        for line in output.splitlines():
            match = STAT_LINE.search(line)
            if match:
                entries.append((match.group(1), int(match.group(2))))

    pattern = re.compile(r"^user>>>(.+)>>>traffic>>>(uplink|downlink)$")
    for name, value in entries:
        match = pattern.match(name)
        if not match:
            continue
        email, direction = match.group(1), match.group(2)
        bucket = users.setdefault(email, {"up": 0, "down": 0})
        bucket["up" if direction == "uplink" else "down"] += value
    return users


# --------------------------------------------------------------------------
# Основной цикл
# --------------------------------------------------------------------------


def apply_config(config: dict) -> bool:
    global LAST_ERROR
    if not write_config(config, CONFIG_PATH):
        LAST_ERROR = f"не удалось записать {CONFIG_PATH}"
        return False
    ok, message = xray.test_config(CONFIG_PATH)
    if not ok:
        log(f"xray -test отклонил конфиг: {message}", "error")
        LAST_ERROR = f"xray -test: {message}"[:400]
        return False
    log("конфиг проверен и обновлён")
    xray.restart()
    LAST_ERROR = ""
    return True


def loop() -> int:
    global APPLIED_REVISION
    if not PANEL_URL:
        log("DFX_PANEL_URL не задан", "error")
        return 2
    if not NODE_TOKEN:
        log("DFX_NODE_TOKEN не задан", "error")
        return 2

    log(f"панель: {PANEL_URL}")
    log(f"конфиг: {CONFIG_PATH}, xray: {XRAY_BIN}{' (dry-run)' if DRY_RUN else ''}")

    revision = ""
    poll = POLL
    fail_count = 0
    users_count = 0
    started_at = time.time()

    while not STOP:
        try:
            payload = fetch_config()
            fail_count = 0
            node = payload.get("node", {})
            new_revision = payload.get("revision", "")
            poll = int(payload.get("poll_interval") or POLL)
            users_count = int(payload.get("users") or 0)
            log(
                f"нода «{node.get('name', '?')}» · ревизия {new_revision} · "
                f"клиентов {users_count}",
                "debug",
            )
            if new_revision != revision or not os.path.isfile(CONFIG_PATH):
                if apply_config(payload.get("config") or {}):
                    revision = new_revision
                    APPLIED_REVISION = new_revision
                else:
                    log("конфиг не применён, остаётся предыдущий", "error")
            xray.ensure_running()

            stats = query_stats()
            if stats:
                total_up = sum(item["up"] for item in stats.values())
                total_down = sum(item["down"] for item in stats.values())
                response = report(
                    {
                        "xray_version": xray.detect_version(),
                        "uptime": int(time.time() - started_at),
                        "stats": {
                            "users": stats,
                            "node": {"up": total_up, "down": total_down},
                        },
                        **system_metrics(),
                    }
                )
                if response.get("blocked"):
                    log(f"исчерпали лимит: {', '.join(response['blocked'])}", "warn")
                if response.get("revision") and response["revision"] != revision:
                    revision = ""  # заставит перечитать конфиг на следующем круге
                log(
                    f"отправлено: ↑{total_up} ↓{total_down} байт, "
                    f"клиентов в статистике {len(stats)}",
                    "debug",
                )
            else:
                heartbeat(
                    {
                        "xray_version": xray.detect_version(),
                        "uptime": int(time.time() - started_at),
                        **system_metrics(),
                    }
                )
        except urllib.error.HTTPError as exc:
            fail_count += 1
            body = ""
            with contextlib.suppress(OSError):
                body = exc.read().decode("utf-8", "replace")[:200]
            log(f"HTTP {exc.code} от панели: {body}", "error")
            if exc.code == 401:
                log("токен ноды отклонён панелью — проверьте DFX_NODE_TOKEN", "error")
                time.sleep(min(poll, 60))
                continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            fail_count += 1
            log(f"нет связи с панелью ({exc}) · попытка {fail_count}", "warn")
        except json.JSONDecodeError as exc:
            log(f"некорректный ответ панели: {exc}", "error")
        except Exception as exc:
            log(f"непредвиденная ошибка: {exc!r}", "error")

        xray.ensure_running()
        delay = poll if fail_count == 0 else min(poll * min(fail_count, 6), 300)
        for _ in range(int(delay)):
            if STOP:
                break
            time.sleep(1)
    return 0


xray = XrayProcess()


def handle_stop(signum, frame) -> None:
    global STOP
    STOP = True
    log(f"получен сигнал {signum}, завершаюсь")
    xray.stop()


def main() -> int:
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    if not DRY_RUN:
        xray.start()
    else:
        log("режим dry-run: xray не запускается", "warn")
    try:
        return loop()
    finally:
        xray.stop()


if __name__ == "__main__":
    raise SystemExit(main())
