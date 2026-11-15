"""Уведомления: Telegram, вебхук и проверка событий (ноды, лимиты, обновления)."""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config, db, repo, updates
from .utils import iso

EVENTS = {
    "node_offline": "Сервер не в сети",
    "node_recovered": "Сервер вернулся в строй",
    "user_limit": "Клиент исчерпал лимит",
    "update_available": "Доступно обновление панели",
}


# --------------------------------------------------------------------------
# Настройки и отправка
# --------------------------------------------------------------------------


def settings() -> dict[str, Any]:
    data = db.get_settings()
    enabled_events = {
        item.strip()
        for item in (data.get("notify_events") or "").split(",")
        if item.strip()
    }
    return {
        "enabled": data.get("notify_enabled") == "1",
        "telegram_token": (data.get("notify_telegram_token") or "").strip(),
        "telegram_chat": (data.get("notify_telegram_chat") or "").strip(),
        "webhook": (data.get("notify_webhook") or "").strip(),
        "events": enabled_events or set(EVENTS),
    }


def serialize_settings() -> dict[str, Any]:
    data = settings()
    return {
        "enabled": data["enabled"],
        "telegram_token": data["telegram_token"],
        "telegram_chat": data["telegram_chat"],
        "webhook": data["webhook"],
        "events": sorted(data["events"]),
        "available_events": EVENTS,
    }


def _post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> bool:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"DF_Xray-Panel/{config.APP_VERSION}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _send_telegram(token: str, chat: str, text: str) -> bool:
    if not token or not chat:
        return False
    return _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
    )


def _send_webhook(url: str, payload: dict[str, Any]) -> bool:
    if not url:
        return False
    return _post_json(url, payload)


def deliver(event: str, title: str, message: str, **extra: Any) -> dict[str, bool]:
    """Отправить уведомление по всем настроенным каналам (без проверки настроек)."""
    cfg = settings()
    text = f"<b>{title}</b>\n{message}\n<i>{iso()}</i>"
    payload = {
        "event": event,
        "title": title,
        "message": message,
        "version": config.APP_VERSION,
        "at": iso(),
        **extra,
    }
    results = {
        "telegram": _send_telegram(cfg["telegram_token"], cfg["telegram_chat"], text),
        "webhook": _send_webhook(cfg["webhook"], payload),
    }
    return results


def notify(event: str, title: str, message: str, **extra: Any) -> dict[str, bool]:
    cfg = settings()
    if not cfg["enabled"] or event not in cfg["events"]:
        return {"telegram": False, "webhook": False}
    return deliver(event, title, message, **extra)


def test() -> dict[str, Any]:
    cfg = settings()
    if not cfg["telegram_token"] and not cfg["webhook"]:
        return {"ok": False, "error": "Не заданы Telegram-токен и вебхук"}
    results = deliver(
        "test",
        "Проверка уведомлений",
        f"Панель {config.APP_VERSION} отправляет тестовое сообщение.",
    )
    return {"ok": any(results.values()), "channels": results}


# --------------------------------------------------------------------------
# Проверка событий
# --------------------------------------------------------------------------


def _state() -> dict[str, Any]:
    try:
        raw = json.loads(db.get_setting("notify_state") or "{}")
    except (ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("nodes", {})
    raw.setdefault("users", {})
    raw.setdefault("updates", "")
    return raw


def _save_state(state: dict[str, Any]) -> None:
    db.set_setting("notify_state", json.dumps(state, ensure_ascii=False))


def check_once() -> list[dict[str, Any]]:
    """Сравнить текущее состояние с прошлым и отправить новые события."""
    cfg = settings()
    if not cfg["enabled"]:
        return []
    state = _state()
    sent: list[dict[str, Any]] = []

    for node in repo.list_nodes():
        key = str(node["id"])
        health = node["health"]
        previous = state["nodes"].get(key, "")
        if health in ("offline", "degraded"):
            if previous != health and "node_offline" in cfg["events"]:
                title = "Сервер не в сети" if health == "offline" else "Xray остановлен"
                message = f"{node['name']} ({node['address']}:{node['port']})"
                if node["last_seen"]:
                    message += f"\nпоследняя связь: {node['last_seen']}"
                if node["last_error"]:
                    message += f"\nошибка: {node['last_error']}"
                notify("node_offline", title, message, node_id=node["id"])
                state["nodes"][key] = health
                sent.append({"event": "node_offline", "node": node["name"], "health": health})
        elif previous:
            state["nodes"].pop(key, None)
            if "node_recovered" not in cfg["events"]:
                continue
            notify(
                "node_recovered",
                "Сервер снова в сети",
                f"{node['name']} ({node['address']}:{node['port']}) отвечает",
                node_id=node["id"],
            )
            sent.append({"event": "node_recovered", "node": node["name"]})

    for row in db.all("SELECT * FROM users"):
        status = repo.user_status(row)
        key = str(row["id"])
        previous = state["users"].get(key, "")
        if status in ("limited", "expired"):
            if previous != status and "user_limit" in cfg["events"]:
                title = "Клиент исчерпал лимит" if status == "limited" else "Подписка истекла"
                notify("user_limit", title, f"{row['username']}", user_id=row["id"])
                state["users"][key] = status
                sent.append({"event": "user_limit", "user": row["username"], "status": status})
        elif previous:
            state["users"].pop(key, None)

    info = updates.cached()
    latest = (info.get("latest") or "").strip()
    if latest and updates.is_newer(latest, config.APP_VERSION):
        if state.get("updates") != latest and "update_available" in cfg["events"]:
            notify(
                "update_available",
                "Доступно обновление панели",
                f"{config.APP_VERSION} → {latest}",
                url=info.get("url", ""),
            )
            state["updates"] = latest
            sent.append({"event": "update_available", "latest": latest})
    elif not latest:
        state["updates"] = ""

    _save_state(state)
    return sent


# --------------------------------------------------------------------------
# Фоновый воркер
# --------------------------------------------------------------------------

_worker_started = False
_worker_lock = threading.Lock()


def start_worker(interval: float = 90.0) -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def loop() -> None:
        time.sleep(5)
        while True:
            try:
                check_once()
            except Exception as exc:  # воркер не должен падать из-за одного события
                sys.stderr.write(f"[dfxray] notify: {exc!r}\n")
            time.sleep(max(15.0, interval))

    threading.Thread(target=loop, name="dfxray-notify", daemon=True).start()


def pending_state() -> dict[str, Any]:
    """Для отладки и тестов: сколько событий уже отправлено."""
    state = _state()
    return {
        "nodes": len(state["nodes"]),
        "users": len(state["users"]),
        "updates": state.get("updates") or "",
    }
