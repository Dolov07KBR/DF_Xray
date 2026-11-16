"""Метрики железа: процессор, память, диск — панели и нод.

Читает /proc (Linux) без внешних зависимостей и складывает замеры в таблицу
`metrics`, чтобы на дашборде были графики за последний час, а не одно число.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import threading
import time
from typing import Any

from . import repo

_last_cpu: tuple[int, int] | None = None
_sampler_started = False
_sampler_lock = threading.Lock()


def _cpu_times() -> tuple[int, int] | None:
    """(busy, total) тики процессора из /proc/stat."""
    try:
        with open("/proc/stat", encoding="utf-8") as handle:
            parts = handle.readline().split()
    except OSError:
        return None
    if not parts or parts[0] != "cpu":
        return None
    values = [int(v) for v in parts[1:] if v.isdigit()]
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total - idle, total


def cpu_percent() -> float:
    """Загрузка CPU в процентах между двумя вызовами (первый вызов — среднее с загрузки)."""
    global _last_cpu
    current = _cpu_times()
    if current is None:
        with contextlib.suppress(OSError):
            return round(os.getloadavg()[0] * 100 / max(1, os.cpu_count() or 1), 1)
        return 0.0
    busy, total = current
    if _last_cpu is None:
        try:
            with open("/proc/uptime", encoding="utf-8") as handle:
                uptime = float(handle.read().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = 0.0
        load = 0.0
        with contextlib.suppress(OSError):
            load = os.getloadavg()[0]
        _last_cpu = (busy, total)
        if uptime > 0:
            return round(max(0.0, min(100.0, load * 100 / max(1, os.cpu_count() or 1))), 1)
        return 0.0
    busy_delta = busy - _last_cpu[0]
    total_delta = total - _last_cpu[1]
    _last_cpu = (busy, total)
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, busy_delta * 100 / total_delta)), 1)


def memory() -> dict[str, int]:
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                info[key.strip()] = int(rest.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {"used": 0, "total": 0}
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return {"used": max(0, total - available), "total": total}


def uptime() -> int:
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            return int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def disk(path: str = "/") -> dict[str, int]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {"used": 0, "total": 0}
    return {"used": usage.used, "total": usage.total}


def host_snapshot() -> dict[str, Any]:
    """Текущий срез состояния сервера панели."""
    mem = memory()
    load1 = 0.0
    with contextlib.suppress(OSError):
        load1 = round(os.getloadavg()[0], 2)
    return {
        "cpu": cpu_percent(),
        "cores": os.cpu_count() or 1,
        "mem_used": mem["used"],
        "mem_total": mem["total"],
        "mem_percent": round(mem["used"] * 100 / mem["total"], 1) if mem["total"] else 0.0,
        "load1": load1,
        "uptime": uptime(),
        "disk": disk(),
        "ts": int(time.time()),
    }


def sample_panel() -> dict[str, Any]:
    """Снять метрики панели и записать их в историю."""
    snapshot = host_snapshot()
    repo.add_metrics(
        repo.PANEL_METRICS_ID,
        snapshot["cpu"],
        snapshot["mem_used"],
        snapshot["mem_total"],
        snapshot["load1"],
    )
    return snapshot


def start_sampler(interval: float = 20.0) -> None:
    """Фоновый сбор метрик панели (и очистка старой истории)."""
    global _sampler_started
    with _sampler_lock:
        if _sampler_started:
            return
        _sampler_started = True

    def loop() -> None:
        time.sleep(2)
        ticks = 0
        while True:
            try:
                sample_panel()
                ticks += 1
                if ticks % 180 == 0:  # раз в час
                    repo.prune_metrics(48)
            except Exception as exc:  # сбор метрик не должен ронять воркер
                sys.stderr.write(f"[dfxray] metrics: {exc!r}\n")
            time.sleep(max(5.0, interval))

    threading.Thread(target=loop, name="dfxray-metrics", daemon=True).start()


def series(node_id: int, minutes: int = 60) -> list[dict[str, Any]]:
    return repo.metrics_series(node_id, minutes)
