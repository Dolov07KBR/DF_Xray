"""Telegram-бот для продажи подписок прямо из панели.

Работает на стандартной библиотеке: long polling `getUpdates`, инлайн-кнопки,
счёт Telegram Stars (валюта XTR, без платёжного провайдера) или ручное
подтверждение оплаты администратором в панели.

Команды и сценарии:

* `/start` — приветствие и меню: купить, пробный период, моя подписка, поддержка;
* «Купить» → тарифы из настроек → счёт Stars либо заявка на ручную оплату;
* «Пробный» → одноразовый тестовый доступ на N дней и N ГБ;
* `/my` — ссылка подписки, остаток лимита и срок;
* `/stats`, `/orders`, `/approve <id>`, `/deny <id>` — для администратора.

Панель не требует вебхука и белого IP: бот сам опрашивает Telegram.
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import db, repo
from .utils import iso, to_bool, to_int

API_ROOT = "https://api.telegram.org"
POLL_TIMEOUT = 25
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_stop = threading.Event()


# --------------------------------------------------------------------------
# Настройки
# --------------------------------------------------------------------------

DEFAULT_PLANS = [
    {"id": "m1", "title": "1 месяц", "days": 30, "gb": 100, "price": 199, "stars": 199},
    {"id": "m3", "title": "3 месяца", "days": 90, "gb": 400, "price": 499, "stars": 499},
    {"id": "m12", "title": "12 месяцев", "days": 365, "gb": 2000, "price": 1499, "stars": 1499},
]


def settings() -> dict[str, Any]:
    data = db.get_settings()
    plans: list[dict[str, Any]] = []
    try:
        raw = json.loads(data.get("bot_plans") or "[]")
        if isinstance(raw, list):
            plans = [item for item in raw if isinstance(item, dict) and item.get("id")]
    except (ValueError, TypeError):
        plans = []
    if not plans:
        plans = [dict(item) for item in DEFAULT_PLANS]
    return {
        "enabled": data.get("bot_enabled") == "1",
        "token": (data.get("bot_token") or "").strip(),
        "username": (data.get("bot_username") or "").strip(),
        "admin_chat": (data.get("bot_admin_chat") or "").strip(),
        "welcome": data.get("bot_welcome") or "",
        "support": (data.get("bot_support") or "").strip(),
        "trial_days": to_int(data.get("bot_trial_days"), 3),
        "trial_gb": to_int(data.get("bot_trial_gb"), 10),
        "trial_enabled": data.get("bot_trial_enabled") == "1",
        "plans": plans,
        "payment_mode": (data.get("bot_payment_mode") or "stars").strip(),
        "manual_note": data.get("bot_manual_note") or "",
        "last_error": data.get("bot_last_error") or "",
    }


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    mapping = {
        "enabled": "bot_enabled",
        "token": "bot_token",
        "admin_chat": "bot_admin_chat",
        "welcome": "bot_welcome",
        "support": "bot_support",
        "trial_days": "bot_trial_days",
        "trial_gb": "bot_trial_gb",
        "trial_enabled": "bot_trial_enabled",
        "payment_mode": "bot_payment_mode",
        "manual_note": "bot_manual_note",
    }
    for key, setting in mapping.items():
        if key not in payload:
            continue
        value = payload[key]
        if key in ("enabled", "trial_enabled"):
            values[setting] = "1" if to_bool(value) else "0"
        elif key in ("trial_days", "trial_gb"):
            values[setting] = str(max(0, to_int(value)))
        elif key == "payment_mode":
            values[setting] = "manual" if str(value) == "manual" else "stars"
        else:
            values[setting] = str(value or "").strip()
    if "plans" in payload and isinstance(payload["plans"], list):
        clean = []
        for index, item in enumerate(payload["plans"][:10]):
            if not isinstance(item, dict):
                continue
            plan_id = str(item.get("id") or f"p{index + 1}").strip()[:16]
            days = max(1, to_int(item.get("days"), 30))
            clean.append(
                {
                    "id": plan_id,
                    "title": str(item.get("title") or f"{days} дней")[:40],
                    "days": days,
                    "gb": max(0, to_int(item.get("gb"))),
                    "price": max(0, to_int(item.get("price"))),
                    "stars": max(0, to_int(item.get("stars") or item.get("price"))),
                }
            )
        values["bot_plans"] = json.dumps(clean, ensure_ascii=False)
    db.update_settings(values)
    return settings()


# --------------------------------------------------------------------------
# Telegram API
# --------------------------------------------------------------------------


def _call(method: str, payload: dict[str, Any] | None = None, token: str = "", timeout: int = 30) -> dict:
    token = token or settings()["token"]
    if not token:
        raise RuntimeError("Не задан токен бота")
    url = f"{API_ROOT}/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    result = json.loads(raw.decode("utf-8") or "{}")
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or "Telegram вернул ошибку")
    return result.get("result") or {}


def bot_info(token: str = "") -> dict[str, Any]:
    """Проверка токена: getMe."""
    result = _call("getMe", token=token, timeout=15)
    return {"id": result.get("id"), "username": result.get("username") or "",
            "name": result.get("first_name") or ""}


def _send(chat_id: int | str, text: str, keyboard: list | None = None, parse_mode: str = "HTML") -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        _call("sendMessage", payload)
    except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
        _log_error(f"sendMessage: {exc}")


def _edit(chat_id: int, message_id: int, text: str, keyboard: list | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    with contextlib.suppress(RuntimeError, urllib.error.URLError, TimeoutError):
        _call("editMessageText", payload)


def _answer(callback_id: str, text: str = "", alert: bool = False) -> None:
    with contextlib.suppress(RuntimeError, urllib.error.URLError, TimeoutError):
        _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200],
                                      "show_alert": alert})


def _log_error(message: str) -> None:
    db.update_settings({"bot_last_error": message[:300]})
    sys.stderr.write(f"[dfxray] bot: {message}\n")


# --------------------------------------------------------------------------
# Состояние пользователя и заказы
# --------------------------------------------------------------------------


def bot_user(tg_id: int) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM bot_users WHERE tg_id = ?", (tg_id,))
    return dict(row) if row else None


def touch_bot_user(tg_id: int, username: str = "", full_name: str = "") -> dict[str, Any]:
    row = bot_user(tg_id)
    now_iso = iso()
    if row is None:
        db.run(
            "INSERT INTO bot_users(tg_id, username, full_name, created_at, last_seen) "
            "VALUES(?,?,?,?,?)",
            (tg_id, username[:64], full_name[:80], now_iso, now_iso),
        )
    else:
        db.run(
            "UPDATE bot_users SET username = ?, full_name = ?, last_seen = ? WHERE tg_id = ?",
            (username[:64] or row["username"], full_name[:80] or row["full_name"], now_iso, tg_id),
        )
    return bot_user(tg_id) or {}


def plan_by_id(plan_id: str) -> dict[str, Any] | None:
    for plan in settings()["plans"]:
        if str(plan.get("id")) == str(plan_id):
            return plan
    return None


def create_order(tg_id: int, plan: dict[str, Any], username: str = "", note: str = "") -> int:
    stamp = iso()
    order_id = db.run(
        "INSERT INTO bot_orders(tg_id, username, plan_id, title, amount, currency, days, "
        "limit_gb, status, payload, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            tg_id,
            username[:64],
            str(plan.get("id") or ""),
            str(plan.get("title") or "")[:60],
            float(plan.get("stars") or plan.get("price") or 0),
            "XTR",
            to_int(plan.get("days"), 30),
            to_int(plan.get("gb"), 0),
            "pending",
            "",
            note[:200],
            stamp,
        ),
    )
    return int(order_id)


def order(order_id: int) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM bot_orders WHERE id = ?", (order_id,))
    return dict(row) if row else None


def list_orders(limit: int = 30) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM bot_orders ORDER BY id DESC LIMIT ?", (limit,))
    items = []
    for row in rows:
        item = dict(row)
        user = repo.get_user(item["user_id"]) if item.get("user_id") else None
        item["panel_user"] = user["username"] if user else ""
        items.append(item)
    return items


def orders_stats() -> dict[str, Any]:
    paid = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM bot_orders "
                  "WHERE status = 'paid'") or {"n": 0, "total": 0}
    pending = db.one("SELECT COUNT(*) AS n FROM bot_orders WHERE status = 'pending'") or {"n": 0}
    users = db.one("SELECT COUNT(*) AS n FROM bot_users") or {"n": 0}
    return {"paid": to_int(paid["n"]), "revenue": float(paid["total"] or 0),
            "pending": to_int(pending["n"]), "clients": to_int(users["n"])}


# --------------------------------------------------------------------------
# Выдача доступа
# --------------------------------------------------------------------------


def _username_for(tg_id: int, username: str) -> str:
    base = f"tg_{username}" if username else f"tg_{tg_id}"
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in "_-")[:40] or f"tg_{tg_id}"
    candidate = cleaned
    suffix = 1
    while db.one("SELECT 1 FROM users WHERE username = ?", (candidate,)):
        suffix += 1
        candidate = f"{cleaned}_{suffix}"[:64]
    return candidate


def grant_access(tg_id: int, days: int, limit_gb: int, note: str = "",
                 username: str = "") -> dict[str, Any]:
    """Создать клиента панели или продлить существующего."""
    record = touch_bot_user(tg_id, username=username)
    panel_user = repo.get_user(record["user_id"]) if record.get("user_id") else None
    if panel_user is not None:
        repo.extend_user(panel_user["id"], max(1, days))
        if limit_gb:
            extra = limit_gb * 1024 ** 3
            db.run(
                "UPDATE users SET limit_bytes = limit_bytes + ?, updated_at = ? WHERE id = ?",
                (extra, iso(), panel_user["id"]),
            )
        user_id = panel_user["id"]
    else:
        user_id = repo.create_user(
            {
                "username": _username_for(tg_id, username),
                "email": f"tg{tg_id}@telegram.local",
                "days": max(1, days),
                "limit_gb": limit_gb,
                "note": note or f"Telegram @{username or tg_id}",
            }
        )
        db.run("UPDATE bot_users SET user_id = ? WHERE tg_id = ?", (user_id, tg_id))

    user = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    base_url = (db.get_setting("public_base_url") or "").rstrip("/")
    sub_url = f"{base_url}/sub/{user['sub_token']}" if base_url else f"/sub/{user['sub_token']}"
    limit = to_int(user["limit_bytes"])
    used = to_int(user["up_bytes"]) + to_int(user["down_bytes"])
    return {
        "user_id": user_id,
        "username": user["username"],
        "sub_url": sub_url,
        "expires_at": user["expires_at"] or "",
        "limit_gb": round(limit / 1024 ** 3, 1) if limit else 0,
        "used_gb": round(used / 1024 ** 3, 2),
    }


def mark_paid(order_id: int, note: str = "") -> dict[str, Any] | None:
    row = order(order_id)
    if row is None:
        return None
    if row["status"] == "paid":
        return row
    access = grant_access(row["tg_id"], to_int(row["days"]), to_int(row["limit_gb"]),
                          note=note or f"Заказ #{order_id}", username=row["username"])
    db.run(
        "UPDATE bot_orders SET status = 'paid', user_id = ?, paid_at = ? WHERE id = ?",
        (access["user_id"], iso(), order_id),
    )
    _notify_admin(
        f"💰 Оплачен заказ <b>#{order_id}</b>\n"
        f"Тариф: {row['title']} · {row['days']} дн · {int(row['amount'])} ⭐\n"
        f"Клиент панели: <code>{access['username']}</code>"
    )
    fresh = order(order_id) or row
    return {**fresh, "access": access}


def deny_order(order_id: int) -> None:
    db.run("UPDATE bot_orders SET status = 'denied' WHERE id = ? AND status = 'pending'", (order_id,))


def _notify_admin(text: str) -> None:
    admin = settings()["admin_chat"]
    if admin:
        _send(admin, text)


# --------------------------------------------------------------------------
# Сценарии бота
# --------------------------------------------------------------------------


def _menu_keyboard(tg_id: int) -> list[list[dict[str, str]]]:
    conf = settings()
    keyboard = [[{"text": "🚀 Купить подписку", "callback_data": "buy"}]]
    row = bot_user(tg_id) or {}
    if conf["trial_enabled"] and not to_int(row.get("trial_used")):
        keyboard.append([{"text": "🎁 Пробный доступ", "callback_data": "trial"}])
    keyboard.append([{"text": "📱 Моя подписка", "callback_data": "my"}])
    if conf["support"]:
        support = conf["support"]
        if support.startswith("http") or support.startswith("tg://"):
            keyboard.append([{"text": "🆘 Поддержка", "url": support}])
        else:
            keyboard.append([{"text": "🆘 Поддержка", "callback_data": "support"}])
    return keyboard


def _plans_text() -> str:
    conf = settings()
    lines = ["<b>Тарифы</b>", ""]
    for plan in conf["plans"]:
        gb = f"{plan['gb']} ГБ" if to_int(plan.get("gb")) else "без лимита"
        price = to_int(plan.get("stars") or plan.get("price"))
        unit = "⭐" if conf["payment_mode"] == "stars" else "₽"
        lines.append(f"• <b>{plan['title']}</b> — {to_int(plan['days'])} дн · {gb} · {price} {unit}")
    if conf["payment_mode"] == "manual":
        lines += ["", conf["manual_note"] or "Оплата подтверждается администратором."]
    return "\n".join(lines)


def _plans_keyboard() -> list[list[dict[str, str]]]:
    conf = settings()
    unit = "⭐" if conf["payment_mode"] == "stars" else "₽"
    rows = [
        [{"text": f"{plan['title']} · {to_int(plan.get('stars') or plan.get('price'))} {unit}",
          "callback_data": f"plan:{plan['id']}"}]
        for plan in conf["plans"]
    ]
    rows.append([{"text": "‹ Назад", "callback_data": "menu"}])
    return rows


def _subscription_text(tg_id: int) -> tuple[str, list[list[dict[str, str]]] | None]:
    row = bot_user(tg_id)
    if not row or not row.get("user_id"):
        return "У вас пока нет подписки. Нажмите «🚀 Купить подписку» в меню.", None
    user = repo.get_user(row["user_id"])
    if user is None:
        return "Подписка не найдена в панели — напишите в поддержку.", None
    base_url = (db.get_setting("public_base_url") or "").rstrip("/")
    link = f"{base_url}/sub/{user['sub_token']}" if base_url else f"/sub/{user['sub_token']}"
    limit = to_int(user["limit_bytes"])
    used = to_int(user["up_bytes"]) + to_int(user["down_bytes"])
    used_text = f"{round(used / 1024 ** 3, 2)} ГБ"
    limit_text = f"{round(limit / 1024 ** 3, 1)} ГБ" if limit else "без лимита"
    status = repo.user_status(user)
    text = (
        f"<b>Ваша подписка</b>\n\n"
        f"Логин: <code>{user['username']}</code>\n"
        f"Действует до: <b>{user['expires_at'] or 'бессрочно'}</b>\n"
        f"Трафик: {used_text} из {limit_text}\n"
        f"Статус: {status}\n\n"
        f"Ссылка для клиента:\n<code>{link}</code>"
    )
    keyboard = [[{"text": "🔗 Открыть страницу подписки", "url": link}]] if base_url else []
    keyboard.append([{"text": "‹ В меню", "callback_data": "menu"}])
    return text, keyboard


def handle_update(update: dict[str, Any]) -> None:
    if "callback_query" in update:
        query = update["callback_query"]
        from_user = query.get("from") or {}
        tg_id = to_int(from_user.get("id"))
        data = str(query.get("data") or "")
        _answer(query.get("id") or "")
        touch_bot_user(tg_id, from_user.get("username") or "",
                       " ".join(filter(None, [from_user.get("first_name"),
                                              from_user.get("last_name")]))[:80])
        message = query.get("message") or {}
        chat_id = to_int((message.get("chat") or {}).get("id")) or tg_id
        message_id = to_int(message.get("message_id"))
        if data == "menu":
            if message_id:
                _edit(chat_id, message_id, settings()["welcome"] or "Меню", _menu_keyboard(tg_id))
            else:
                _send(chat_id, settings()["welcome"] or "Меню", _menu_keyboard(tg_id))
            return
        if data == "buy":
            if message_id:
                _edit(chat_id, message_id, _plans_text(), _plans_keyboard())
            else:
                _send(chat_id, _plans_text(), _plans_keyboard())
            return
        if data == "my":
            text, keyboard = _subscription_text(tg_id)
            if message_id:
                _edit(chat_id, message_id, text, keyboard)
            else:
                _send(chat_id, text, keyboard)
            return
        if data == "support":
            _send(chat_id, settings()["support"] or "Поддержка: напишите администратору.")
            return
        if data == "trial":
            _start_trial(tg_id, chat_id, from_user)
            return
        if data.startswith("plan:"):
            _start_purchase(tg_id, chat_id, data.split(":", 1)[1], from_user)
            return
        return

    message = update.get("message") or {}
    chat_id = to_int((message.get("chat") or {}).get("id"))
    from_user = message.get("from") or {}
    tg_id = to_int(from_user.get("id"))
    text = str(message.get("text") or "").strip()
    if not tg_id:
        return
    touch_bot_user(tg_id, from_user.get("username") or "",
                   " ".join(filter(None, [from_user.get("first_name"),
                                          from_user.get("last_name")]))[:80])
    if text in ("/start", "/menu", "start"):
        _send(chat_id, settings()["welcome"] or "Здравствуйте!", _menu_keyboard(tg_id))
        return
    if text == "/my":
        body, keyboard = _subscription_text(tg_id)
        _send(chat_id, body, keyboard)
        return
    if text == "/help":
        _send(chat_id, "Команды: /start — меню, /my — подписка. Поддержка: "
                       f"{settings()['support'] or 'напишите администратору'}.")
        return
    if text.startswith("/"):
        _admin_command(tg_id, chat_id, text)
        return
    _send(chat_id, "Выберите действие в меню 👇", _menu_keyboard(tg_id))


def _start_trial(tg_id: int, chat_id: int, from_user: dict[str, Any]) -> None:
    conf = settings()
    if not conf["trial_enabled"]:
        _send(chat_id, "Пробный доступ сейчас недоступен.")
        return
    row = bot_user(tg_id) or {}
    if to_int(row.get("trial_used")):
        _send(chat_id, "Пробный доступ уже использован. Оформите подписку 🚀")
        return
    access = grant_access(tg_id, conf["trial_days"], conf["trial_gb"],
                          note="Пробный период из Telegram",
                          username=from_user.get("username") or "")
    db.run("UPDATE bot_users SET trial_used = 1 WHERE tg_id = ?", (tg_id,))
    _send(
        chat_id,
        f"🎁 <b>Пробный доступ активирован</b>\n\n"
        f"На {conf['trial_days']} дн · {conf['trial_gb'] or '∞'} ГБ\n\n"
        f"Ссылка подписки:\n<code>{access['sub_url']}</code>\n\n"
        "Добавьте её в клиент (v2rayN, Hiddify, Streisand, v2rayNG).",
        [[{"text": "📱 Моя подписка", "callback_data": "my"}]],
    )
    _notify_admin(f"🎁 Пробный доступ: @{from_user.get('username') or tg_id} "
                  f"({conf['trial_days']} дн)")


def _start_purchase(tg_id: int, chat_id: int, plan_id: str, from_user: dict[str, Any]) -> None:
    plan = plan_by_id(plan_id)
    if plan is None:
        _send(chat_id, "Такого тарифа нет — обновите меню /start")
        return
    conf = settings()
    username = from_user.get("username") or ""
    order_id = create_order(tg_id, plan, username=username)
    if conf["payment_mode"] == "stars":
        try:
            _call(
                "sendInvoice",
                {
                    "chat_id": chat_id,
                    "title": f"VPN · {plan['title']}",
                    "description": f"{to_int(plan['days'])} дней, "
                                   f"{to_int(plan['gb']) or '∞'} ГБ трафика",
                    "payload": f"order:{order_id}",
                    "currency": "XTR",
                    "prices": [{"label": plan["title"], "amount": to_int(plan.get("stars") or 1)}],
                },
            )
            _send(chat_id, "Счёт выставлен ☝️ После оплаты подписка активируется автоматически.")
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            _log_error(f"sendInvoice: {exc}")
            _send(chat_id, "Не удалось выставить счёт. Напишите в поддержку.")
        return
    db.run("UPDATE bot_orders SET status = 'pending' WHERE id = ?", (order_id,))
    _send(
        chat_id,
        f"Заявка <b>#{order_id}</b> создана: {plan['title']} · "
        f"{to_int(plan['days'])} дн · {to_int(plan.get('price') or 0)} ₽\n\n"
        f"{conf['manual_note'] or 'Администратор подтвердит оплату и включит подписку.'}",
    )
    _notify_admin(
        f"🧾 Новая заявка <b>#{order_id}</b>\n"
        f"Тариф: {plan['title']} · {to_int(plan['days'])} дн · "
        f"{to_int(plan.get('price') or 0)} ₽\n"
        f"Клиент: @{username or tg_id} (id {tg_id})\n"
        f"Подтвердить: /approve {order_id}"
    )


def _admin_command(tg_id: int, chat_id: int, text: str) -> None:
    conf = settings()
    admin_chat = conf["admin_chat"]
    is_admin = str(tg_id) == str(admin_chat) or str(chat_id) == str(admin_chat)
    if not is_admin and not admin_chat:
        is_admin = True  # админ не задан: первый написавший получает доступ к статистике
    if not is_admin:
        _send(chat_id, "Неизвестная команда. /help — что умеет бот.")
        return
    parts = text.split()
    command = parts[0].lower()
    if command == "/stats":
        stats = orders_stats()
        _send(
            chat_id,
            "<b>Статистика бота</b>\n"
            f"Клиентов: {stats['clients']}\n"
            f"Оплат: {stats['paid']} на {int(stats['revenue'])} ⭐\n"
            f"Ожидают подтверждения: {stats['pending']}",
        )
        return
    if command == "/orders":
        items = list_orders(10)
        if not items:
            _send(chat_id, "Заказов пока нет.")
            return
        lines = ["<b>Последние заказы</b>"]
        for item in items:
            lines.append(
                f"#{item['id']} · {item['title']} · {int(item['amount'])} ⭐ · "
                f"{item['status']} · @{item['username'] or item['tg_id']}"
            )
        _send(chat_id, "\n".join(lines))
        return
    if command in ("/approve", "/deny"):
        if len(parts) < 2 or not parts[1].isdigit():
            _send(chat_id, f"Использование: {command} <номер заказа>")
            return
        order_id = int(parts[1])
        if command == "/deny":
            deny_order(order_id)
            _send(chat_id, f"Заказ #{order_id} отклонён.")
            return
        paid = mark_paid(order_id)
        if paid is None:
            _send(chat_id, "Заказ не найден.")
            return
        access = paid.get("access") or {}
        _send(
            chat_id,
            f"Заказ #{order_id} подтверждён.\n"
            f"Клиент: <code>{access.get('username', '')}</code>\n"
            f"Ссылка: <code>{access.get('sub_url', '')}</code>",
        )
        _send(
            paid["tg_id"],
            "✅ <b>Оплата подтверждена!</b>\n\n"
            f"Ссылка подписки:\n<code>{access.get('sub_url', '')}</code>\n\n"
            f"Действует до: {access.get('expires_at') or '—'}",
        )
        return
    _send(chat_id, "Команды: /stats, /orders, /approve <id>, /deny <id>")


def handle_pre_checkout(query: dict[str, Any]) -> None:
    payload = str(query.get("invoice_payload") or "")
    order_id = to_int(payload.split(":", 1)[1]) if payload.startswith("order:") else 0
    row = order(order_id) if order_id else None
    if row is None:
        _call("answerPreCheckoutQuery", {
            "pre_checkout_query_id": query.get("id"),
            "ok": False,
            "error_message": "Заказ не найден, создайте его заново",
        })
        return
    _call("answerPreCheckoutQuery", {
        "pre_checkout_query_id": query.get("id"), "ok": True,
    })


def handle_payment(message: dict[str, Any]) -> None:
    payment = message.get("successful_payment") or {}
    payload = str(payment.get("invoice_payload") or "")
    if not payload.startswith("order:"):
        return
    order_id = to_int(payload.split(":", 1)[1])
    paid = mark_paid(order_id, note=f"Telegram Stars {payment.get('total_amount')}")
    chat_id = to_int((message.get("chat") or {}).get("id"))
    if not chat_id:
        return
    if paid is None:
        _send(chat_id, "Оплата получена, но заказ не найден — напишите в поддержку.")
        return
    access = paid.get("access") or {}
    _send(
        chat_id,
        "✅ <b>Оплата получена!</b>\n\n"
        f"Подписка активна до <b>{access.get('expires_at') or '—'}</b>\n"
        f"Ссылка для клиента:\n<code>{access.get('sub_url', '')}</code>",
        [[{"text": "📱 Моя подписка", "callback_data": "my"}]],
    )


# --------------------------------------------------------------------------
# Long polling
# --------------------------------------------------------------------------


def poll_once(offset: int = 0) -> int:
    updates = _call("getUpdates", {"offset": offset, "timeout": POLL_TIMEOUT,
                                   "allowed_updates": ["message", "callback_query",
                                                       "pre_checkout_query"]},
                    timeout=POLL_TIMEOUT + 10)
    if not isinstance(updates, list):
        return offset
    for update in updates:
        offset = max(offset, to_int(update.get("update_id")) + 1)
        try:
            if "pre_checkout_query" in update:
                handle_pre_checkout(update["pre_checkout_query"])
            elif (update.get("message") or {}).get("successful_payment"):
                handle_payment(update["message"])
            else:
                handle_update(update)
        except Exception as exc:  # один сбойный апдейт не должен останавливать бота
            _log_error(f"update {update.get('update_id')}: {exc!r}")
    return offset


def start_worker() -> None:
    """Запустить long polling, если бот включён и токен задан."""
    global _worker
    conf = settings()
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        if not conf["enabled"] or not conf["token"]:
            return
        _stop.clear()

        def loop() -> None:
            offset = to_int(json.loads(db.get_setting("bot_state") or "{}").get("offset"))
            while not _stop.is_set():
                conf_now = settings()
                if not conf_now["enabled"] or not conf_now["token"]:
                    break
                try:
                    offset = poll_once(offset)
                    db.update_settings({"bot_state": json.dumps({"offset": offset}),
                                        "bot_last_error": ""})
                except urllib.error.HTTPError as exc:
                    _log_error(f"HTTP {exc.code}")
                    time.sleep(10)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    _log_error(f"сеть: {exc}")
                    time.sleep(5)
                except RuntimeError as exc:
                    _log_error(str(exc))
                    time.sleep(10)

        _worker = threading.Thread(target=loop, name="dfxray-bot", daemon=True)
        _worker.start()


def stop_worker() -> None:
    global _worker
    _stop.set()
    _worker = None


def restart_worker() -> None:
    stop_worker()
    time.sleep(0.1)
    start_worker()


def status() -> dict[str, Any]:
    conf = settings()
    stats = orders_stats()
    return {
        "enabled": conf["enabled"],
        "running": bool(_worker is not None and _worker.is_alive()),
        "username": conf["username"],
        "token_set": bool(conf["token"]),
        "payment_mode": conf["payment_mode"],
        "last_error": conf["last_error"],
        **stats,
    }
