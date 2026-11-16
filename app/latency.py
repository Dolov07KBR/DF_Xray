"""Замер задержки до нод и сортировка ссылок подписки."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import xray

CACHE_TTL = 300.0
_cache: dict[int, tuple[float, float | None]] = {}
_lock = threading.Lock()


def _probe(node: Any, timeout: float) -> float | None:
    try:
        result = xray.probe(node["address"], int(node["port"]), timeout=timeout)
    except Exception:  # проба не должна ломать выдачу подписки
        return None
    if not result.get("ok"):
        return None
    value = result.get("latency_ms")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def measure(nodes: list[Any], timeout: float = 1.5, workers: int = 8) -> dict[int, float | None]:
    """TCP-задержка до нод в миллисекундах; кэш на CACHE_TTL секунд."""
    now = time.time()
    result: dict[int, float | None] = {}
    pending: list[Any] = []
    with _lock:
        for node in nodes:
            key = int(node["id"])
            cached = _cache.get(key)
            if cached and now - cached[0] < CACHE_TTL:
                result[key] = cached[1]
            else:
                pending.append(node)
    if pending:
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool:
            futures = {pool.submit(_probe, node, timeout): int(node["id"]) for node in pending}
            for future, key in futures.items():
                value = future.result()
                result[key] = value
        with _lock:
            for node in pending:
                _cache[int(node["id"])] = (now, result.get(int(node["id"])))
    return result


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def sort_links(links: list[dict[str, Any]], latencies: dict[int, float | None]) -> list[dict[str, Any]]:
    """Ближайшие ноды первыми, недоступные — в конце; задержка попадает в ссылку."""
    for link in links:
        link["latency_ms"] = latencies.get(int(link["node_id"]))

    def key(link: dict[str, Any]) -> tuple[int, float, str]:
        value = link.get("latency_ms")
        if value is None:
            return (1, 0.0, str(link.get("node_name") or ""))
        return (0, float(value), str(link.get("node_name") or ""))

    return sorted(links, key=key)
