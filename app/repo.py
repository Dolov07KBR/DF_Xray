"""Доступ к данным панели: пользователи, ноды, трафик, журнал."""

from __future__ import annotations

import contextlib
import datetime as dt
import sqlite3
import time
from typing import Any

from . import config, db
from .utils import (
    date_str,
    days_between,
    gb_to_bytes,
    human_size,
    iso,
    new_short_id,
    new_uuid,
    now,
    parse_iso,
    to_bool,
    to_int,
    today_str,
    token,
)

USER_FIELDS = (
    "username",
    "email",
    "uuid",
    "sub_token",
    "flow",
    "limit_bytes",
    "expires_at",
    "enabled",
    "note",
    "device_limit",
    "node_ids",
)

NODE_FIELDS = (
    "name",
    "address",
    "region",
    "port",
    "protocol",
    "cert_file",
    "key_file",
    "transport",
    "security",
    "sni",
    "fingerprint",
    "private_key",
    "public_key",
    "short_id",
    "dest",
    "path",
    "service_name",
    "flow",
    "alpn",
    "enabled",
    "drain",
    "note",
    "sort",
)

#: Актуальные транспорты Xray: HTTP/2 удалён из ядра, вместо него httpupgrade.
TRANSPORTS = ("tcp", "ws", "grpc", "xhttp", "httpupgrade")
SECURITIES = ("reality", "tls", "none")
PROTOCOLS = ("vless", "vmess", "trojan")


# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------


def user_status(row: sqlite3.Row | dict[str, Any]) -> str:
    if not to_int(row["enabled"]):
        return "disabled"
    expires = row["expires_at"]
    if expires and expires < today_str():
        return "expired"
    limit = to_int(row["limit_bytes"])
    used = to_int(row["up_bytes"]) + to_int(row["down_bytes"])
    if limit and used >= limit:
        return "limited"
    return "active"


def serialize_user(
    row: sqlite3.Row | dict[str, Any], base_url: str = ""
) -> dict[str, Any]:
    data = dict(row)
    used = to_int(data.get("up_bytes")) + to_int(data.get("down_bytes"))
    limit = to_int(data.get("limit_bytes"))
    expires_at = data.get("expires_at")
    node_ids = [int(x) for x in (data.get("node_ids") or "").split(",") if x.strip()]
    payload = {
        "id": data["id"],
        "username": data["username"],
        "email": data.get("email") or "",
        "uuid": data["uuid"],
        "sub_token": data["sub_token"],
        "flow": data.get("flow") or "",
        "enabled": bool(to_int(data.get("enabled"))),
        "note": data.get("note") or "",
        "limit_bytes": limit,
        "limit_gb": round(limit / 1024 ** 3, 2) if limit else 0,
        "up_bytes": to_int(data.get("up_bytes")),
        "down_bytes": to_int(data.get("down_bytes")),
        "used_bytes": used,
        "used_human": human_size(used),
        "remaining_bytes": max(limit - used, 0) if limit else 0,
        "usage_percent": round(min(used / limit * 100, 100), 1) if limit else 0,
        "expires_at": expires_at or "",
        "days_left": days_between(expires_at) if expires_at else None,
        "device_limit": to_int(data.get("device_limit")),
        "node_ids": node_ids,
        "group_id": to_int(data.get("group_id")) or None,
        "group_name": data.get("group_name") or "",
        "group_color": data.get("group_color") or "",
        "status": user_status(data),
        "last_online_at": data.get("last_online_at") or "",
        "last_sub_at": data.get("last_sub_at") or "",
        "created_at": data.get("created_at") or "",
        "updated_at": data.get("updated_at") or "",
        "sub_url": f"{base_url}/sub/{data['sub_token']}" if base_url else "",
        "sub_page_url": f"{base_url}/sub/{data['sub_token']}/page" if base_url else "",
    }
    return payload


def list_users(
    q: str = "",
    status: str = "",
    sort: str = "created_desc",
    limit: int = 200,
    offset: int = 0,
    base_url: str = "",
    group_id: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if group_id:
        where.append("u.group_id = ?")
        params.append(group_id)
    if q:
        where.append(
            "(lower(u.username) LIKE ? OR lower(coalesce(u.email,'')) LIKE ? "
            "OR lower(coalesce(u.note,'')) LIKE ? OR u.uuid LIKE ?)"
        )
        pattern = f"%{q.strip().lower()}%"
        params += [pattern, pattern, pattern, f"%{q.strip()}%"]
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.all(
        "SELECT u.*, g.name AS group_name, g.color AS group_color "
        f"FROM users u LEFT JOIN groups g ON g.id = u.group_id {clause} "
        "ORDER BY u.id DESC",
        params,
    )
    items = [serialize_user(r, base_url) for r in rows]
    if status and status != "all":
        items = [u for u in items if u["status"] == status]
    total = len(items)
    reverse = True
    if sort == "traffic_desc":
        items.sort(key=lambda u: u["used_bytes"], reverse=True)
    elif sort == "traffic_asc":
        items.sort(key=lambda u: u["used_bytes"])
    elif sort == "name":
        items.sort(key=lambda u: u["username"].lower())
        reverse = False
    elif sort == "expires":
        items.sort(key=lambda u: (u["expires_at"] or "9999-12-31"))
        reverse = False
    else:
        items.sort(key=lambda u: u["id"], reverse=reverse)
    return items[offset : offset + limit], total


def get_user(user_id: int) -> sqlite3.Row | None:
    return db.one(
        "SELECT u.*, g.name AS group_name, g.color AS group_color "
        "FROM users u LEFT JOIN groups g ON g.id = u.group_id WHERE u.id = ?",
        (user_id,),
    )


def get_user_by_token(sub_token: str) -> sqlite3.Row | None:
    return db.one("SELECT * FROM users WHERE sub_token = ?", (sub_token,))


def _unique_username(base: str) -> str:
    candidate = base.strip() or "user"
    suffix = 1
    while db.one("SELECT 1 FROM users WHERE username = ?", (candidate,)):
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def create_user(payload: dict[str, Any]) -> int:
    username = (payload.get("username") or "").strip()
    if not username:
        raise ValueError("Укажите имя пользователя")
    if len(username) > 64:
        raise ValueError("Имя пользователя слишком длинное")
    if db.one("SELECT 1 FROM users WHERE username = ?", (username,)):
        raise ValueError("Пользователь с таким именем уже существует")
    days = payload.get("days")
    expires_at = payload.get("expires_at")
    if not expires_at and days not in (None, ""):
        days_int = to_int(days)
        expires_at = today_str(days_int) if days_int > 0 else None
    node_ids = payload.get("node_ids") or []
    if isinstance(node_ids, str):
        node_ids = [x for x in node_ids.replace(" ", "").split(",") if x]
    node_ids_text = ",".join(str(to_int(x)) for x in node_ids if to_int(x)) or None
    limit_bytes = gb_to_bytes(payload.get("limit_gb", 0))
    stamp = iso()
    group_id = to_int(payload.get("group_id", 0)) or None
    return db.run(
        """INSERT INTO users(
            username, email, uuid, sub_token, flow, limit_bytes,
            expires_at, enabled, note, device_limit, node_ids, group_id,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            username,
            (payload.get("email") or "").strip() or None,
            payload.get("uuid") or new_uuid(),
            payload.get("sub_token") or token(18),
            (payload.get("flow") or "").strip() or None,
            limit_bytes,
            expires_at or None,
            1 if to_bool(payload.get("enabled", True)) else 0,
            (payload.get("note") or "").strip() or None,
            to_int(payload.get("device_limit", 0)),
            node_ids_text,
            group_id,
            stamp,
            stamp,
        ),
    )


def update_user(user_id: int, payload: dict[str, Any]) -> None:
    row = get_user(user_id)
    if row is None:
        raise ValueError("Пользователь не найден")
    fields: dict[str, Any] = {}
    if "username" in payload:
        username = (payload["username"] or "").strip()
        if not username:
            raise ValueError("Имя пользователя не может быть пустым")
        other = db.one(
            "SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id)
        )
        if other:
            raise ValueError("Такое имя уже занято")
        fields["username"] = username
    if "email" in payload:
        fields["email"] = (payload["email"] or "").strip() or None
    if "note" in payload:
        fields["note"] = (payload["note"] or "").strip() or None
    if "flow" in payload:
        fields["flow"] = (payload["flow"] or "").strip() or None
    if "limit_gb" in payload:
        fields["limit_bytes"] = gb_to_bytes(payload["limit_gb"])
    if "device_limit" in payload:
        fields["device_limit"] = to_int(payload["device_limit"])
    if "expires_at" in payload:
        expires = (payload["expires_at"] or "").strip()
        fields["expires_at"] = expires or None
    if "days" in payload and payload["days"] not in (None, ""):
        days_int = to_int(payload["days"])
        fields["expires_at"] = today_str(days_int) if days_int > 0 else None
    if "group_id" in payload:
        fields["group_id"] = to_int(payload["group_id"]) or None
    if "enabled" in payload:
        fields["enabled"] = 1 if to_bool(payload["enabled"]) else 0
    if "node_ids" in payload:
        node_ids = payload["node_ids"] or []
        if isinstance(node_ids, str):
            node_ids = [x for x in node_ids.replace(" ", "").split(",") if x]
        fields["node_ids"] = (
            ",".join(str(to_int(x)) for x in node_ids if to_int(x)) or None
        )
    if not fields:
        return
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.run(
        f"UPDATE users SET {assignments} WHERE id = ?",
        (*fields.values(), user_id),
    )


def delete_user(user_id: int) -> None:
    db.run("DELETE FROM users WHERE id = ?", (user_id,))


def reset_traffic(user_id: int) -> None:
    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET up_bytes = 0, down_bytes = 0, updated_at = ? WHERE id = ?",
            (iso(), user_id),
        )
        conn.execute("DELETE FROM traffic WHERE user_id = ?", (user_id,))


def extend_user(user_id: int, days: int) -> str:
    row = get_user(user_id)
    if row is None:
        raise ValueError("Пользователь не найден")
    base = parse_iso((row["expires_at"] or "") + "T00:00:00Z")
    current = base.date() if base else now().date()
    current = max(current, now().date())
    new_date = date_str(current + dt.timedelta(days=days))
    db.run(
        "UPDATE users SET expires_at = ?, updated_at = ? WHERE id = ?",
        (new_date, iso(), user_id),
    )
    return new_date


def rotate_uuid(user_id: int) -> str:
    value = new_uuid()
    db.run(
        "UPDATE users SET uuid = ?, updated_at = ? WHERE id = ?",
        (value, iso(), user_id),
    )
    return value


def rotate_sub_token(user_id: int) -> str:
    value = token(18)
    db.run(
        "UPDATE users SET sub_token = ?, updated_at = ? WHERE id = ?",
        (value, iso(), user_id),
    )
    return value


def mark_sub_access(user_id: int) -> None:
    db.run("UPDATE users SET last_sub_at = ? WHERE id = ?", (iso(), user_id))


def mark_online(user_id: int, when: str | None = None) -> None:
    db.run("UPDATE users SET last_online_at = ? WHERE id = ?", (when or iso(), user_id))


# --------------------------------------------------------------------------
# Ноды
# --------------------------------------------------------------------------


def node_status(row: sqlite3.Row | dict[str, Any]) -> str:
    if not to_int(row["enabled"]):
        return "disabled"
    last_seen = parse_iso(row["last_seen"])
    if not last_seen:
        return "unknown"
    delta = (now() - last_seen).total_seconds()
    if delta <= config.NODE_OFFLINE_AFTER_SECONDS:
        return "online"
    return "offline"


def node_health(row: sqlite3.Row | dict[str, Any]) -> str:
    """Здоровье ноды: offline / degraded (Xray не работает) / ok."""
    data = dict(row)
    if not to_int(data.get("enabled")):
        return "disabled"
    status = node_status(data)
    if status != "online":
        return "offline" if status == "offline" else "unknown"
    if data.get("xray_running") is not None and not to_int(data.get("xray_running")):
        return "degraded"
    return "ok"


def serialize_node(row: sqlite3.Row | dict[str, Any], with_secrets: bool = False) -> dict[str, Any]:
    data = dict(row)
    node = {
        "id": data["id"],
        "name": data["name"],
        "address": data["address"],
        "region": data.get("region") or "",
        "port": to_int(data["port"]),
        "protocol": data.get("protocol") or "vless",
        "transport": data.get("transport") or "tcp",
        "cert_file": data.get("cert_file") or "",
        "key_file": data.get("key_file") or "",
        "security": data.get("security") or "reality",
        "sni": data.get("sni") or "",
        "fingerprint": data.get("fingerprint") or "chrome",
        "public_key": data.get("public_key") or "",
        "short_id": data.get("short_id") or "",
        "dest": data.get("dest") or "",
        "path": data.get("path") or "",
        "service_name": data.get("service_name") or "",
        "flow": data.get("flow") or "",
        "alpn": data.get("alpn") or "",
        "enabled": bool(to_int(data.get("enabled"))),
        "drain": bool(to_int(data.get("drain"))),
        "drained_at": data.get("drained_at") or "",
        "status": node_status(data),
        "health": node_health(data),
        "last_seen": data.get("last_seen") or "",
        "xray_version": data.get("xray_version") or "",
        "up_bytes": to_int(data.get("up_bytes")),
        "down_bytes": to_int(data.get("down_bytes")),
        "note": data.get("note") or "",
        "sort": to_int(data.get("sort")),
        "agent_version": data.get("agent_version") or "",
        "xray_running": None if data.get("xray_running") is None else bool(to_int(data.get("xray_running"))),
        "uptime_seconds": to_int(data.get("uptime_seconds")),
        "load1": float(data.get("load1") or 0),
        "cpu": float(data.get("cpu") or 0),
        "mem_used": to_int(data.get("mem_used")),
        "mem_total": to_int(data.get("mem_total")),
        "mem_percent": (
            round(to_int(data.get("mem_used")) * 100 / to_int(data.get("mem_total")), 1)
            if to_int(data.get("mem_total"))
            else 0.0
        ),
        "cfg_revision": data.get("cfg_revision") or "",
        "applied_at": data.get("applied_at") or "",
        "last_error": data.get("last_error") or "",
        "created_at": data.get("created_at") or "",
    }
    if with_secrets:
        node["private_key"] = data.get("private_key") or ""
        node["agent_token"] = data.get("agent_token") or ""
        node["install_token"] = data.get("install_token") or ""
    return node


def list_nodes(with_secrets: bool = False) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM nodes ORDER BY sort, id")
    return [serialize_node(r, with_secrets) for r in rows]


def get_node(node_id: int) -> sqlite3.Row | None:
    return db.one("SELECT * FROM nodes WHERE id = ?", (node_id,))


def get_node_by_token(agent_token: str) -> sqlite3.Row | None:
    return db.one("SELECT * FROM nodes WHERE agent_token = ?", ((agent_token or "").strip(),))


def node_install_token(node_id: int, rotate: bool = False) -> str:
    """Токен для скрипта установки ноды (не равен токену агента)."""
    row = get_node(node_id)
    if row is None:
        raise ValueError("Нода не найдена")
    existing = (row["install_token"] or "").strip()
    if existing and not rotate:
        return existing
    value = token(24)
    db.run("UPDATE nodes SET install_token = ? WHERE id = ?", (value, node_id))
    return value


def get_node_by_install_token(install_token: str) -> sqlite3.Row | None:
    value = (install_token or "").strip()
    if not value:
        return None
    return db.one("SELECT * FROM nodes WHERE install_token = ?", (value,))


def create_node(payload: dict[str, Any]) -> int:
    name = (payload.get("name") or "").strip()
    address = (payload.get("address") or "").strip()
    if not name:
        raise ValueError("Укажите название ноды")
    if not address:
        raise ValueError("Укажите адрес ноды")
    transport = payload.get("transport") or "tcp"
    security = payload.get("security") or "reality"
    protocol = payload.get("protocol") or "vless"
    if protocol not in PROTOCOLS:
        raise ValueError("Неизвестный протокол")
    if transport not in TRANSPORTS:
        raise ValueError("Неизвестный транспорт")
    if security not in SECURITIES:
        raise ValueError("Неизвестный тип безопасности")
    stamp = iso()
    node_id = db.run(
        """INSERT INTO nodes(
            name, address, region, port, protocol, transport, security, sni, fingerprint,
            private_key, public_key, short_id, dest, path, service_name, flow,
            alpn, cert_file, key_file, enabled, note, sort, agent_token, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            address,
            (payload.get("region") or "").strip() or None,
            to_int(payload.get("port"), 443),
            protocol,
            transport,
            security,
            (payload.get("sni") or "").strip() or None,
            (payload.get("fingerprint") or "chrome").strip(),
            (payload.get("private_key") or "").strip() or None,
            (payload.get("public_key") or "").strip() or None,
            (payload.get("short_id") or new_short_id(8)).strip(),
            (payload.get("dest") or "").strip() or None,
            (payload.get("path") or "/").strip() or None,
            (payload.get("service_name") or "").strip() or None,
            (payload.get("flow") or "").strip() or None,
            (payload.get("alpn") or "").strip() or None,
            (payload.get("cert_file") or "").strip() or None,
            (payload.get("key_file") or "").strip() or None,
            1 if to_bool(payload.get("enabled", True)) else 0,
            (payload.get("note") or "").strip() or None,
            to_int(payload.get("sort")),
            payload.get("agent_token") or token(20),
            stamp,
            stamp,
        ),
    )
    return node_id


def update_node(node_id: int, payload: dict[str, Any]) -> None:
    row = get_node(node_id)
    if row is None:
        raise ValueError("Нода не найдена")
    fields: dict[str, Any] = {}
    for key in NODE_FIELDS:
        if key not in payload:
            continue
        if key in ("enabled", "drain"):
            fields[key] = 1 if to_bool(payload[key]) else 0
            if key == "drain":
                fields["drained_at"] = iso() if fields[key] else None
        elif key == "port":
            fields[key] = to_int(payload[key], 443)
        elif key in ("sort",):
            fields[key] = to_int(payload[key])
        elif key == "transport":
            if payload[key] not in TRANSPORTS:
                raise ValueError("Неизвестный транспорт")
            fields[key] = payload[key]
        elif key == "protocol":
            if payload[key] not in PROTOCOLS:
                raise ValueError("Неизвестный протокол")
            fields[key] = payload[key]
        elif key == "security":
            if payload[key] not in SECURITIES:
                raise ValueError("Неизвестный тип безопасности")
            fields[key] = payload[key]
        else:
            value = payload[key]
            fields[key] = value.strip() if isinstance(value, str) and value.strip() else (
                None if value == "" else value
            )
    if not fields:
        return
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE nodes SET {assignments} WHERE id = ?", (*fields.values(), node_id))


def traffic_by_node(days: int = 14) -> list[dict[str, Any]]:
    """Трафик по нодам за период (для дашборда мультисерверной панели)."""
    rows = db.all(
        "SELECT node_id, SUM(up + down) AS total FROM traffic WHERE day >= ? GROUP BY node_id",
        (today_str(-(max(1, days) - 1)),),
    )
    totals = {to_int(row["node_id"]): to_int(row["total"]) for row in rows}
    result = []
    for node in list_nodes():
        result.append(
            {
                "id": node["id"],
                "name": node["name"],
                "status": node["status"],
                "health": node["health"],
                "total": totals.get(node["id"], 0),
                "users_count": len(node_traffic_users(node["id"])),
            }
        )
    result.sort(key=lambda item: item["total"], reverse=True)
    return result


def replace_user_node(from_node_id: int, to_node_id: int) -> int:
    """Перевести клиентов, закреплённых за нодой, на другую ноду."""
    moved = 0
    rows = db.all("SELECT id, node_ids FROM users")
    for row in rows:
        raw = (row["node_ids"] or "").strip()
        if not raw:
            continue
        ids = [item.strip() for item in raw.split(",") if item.strip()]
        if str(from_node_id) not in ids:
            continue
        result: list[str] = []
        for item in ids:
            value = str(to_node_id) if item == str(from_node_id) else item
            if value not in result:
                result.append(value)
        db.run("UPDATE users SET node_ids = ? WHERE id = ?", (",".join(result), row["id"]))
        moved += 1
    return moved


def delete_node(node_id: int) -> None:
    db.run("DELETE FROM nodes WHERE id = ?", (node_id,))
    db.run("DELETE FROM traffic WHERE node_id = ?", (node_id,))


def update_node_metrics(node_id: int, payload: dict[str, Any]) -> None:
    """Принять heartbeat агента: версии, состояние Xray, железо, ревизия конфига."""
    fields: dict[str, Any] = {"last_seen": iso(), "status": "online"}

    version = (payload.get("xray_version") or "").strip()[:40]
    if version:
        fields["xray_version"] = version
    agent_version = (payload.get("agent_version") or "").strip()[:40]
    if agent_version:
        fields["agent_version"] = agent_version
    if "xray_running" in payload:
        fields["xray_running"] = 1 if to_bool(payload.get("xray_running")) else 0
    if "uptime" in payload:
        fields["uptime_seconds"] = to_int(payload.get("uptime"))
    if "load1" in payload:
        with contextlib.suppress(TypeError, ValueError):
            fields["load1"] = max(0.0, float(payload.get("load1") or 0))
    memory = payload.get("memory") or {}
    cpu = None
    if isinstance(memory, dict):
        if memory.get("used") is not None:
            fields["mem_used"] = max(0, to_int(memory.get("used")))
        if memory.get("total") is not None:
            fields["mem_total"] = max(0, to_int(memory.get("total")))
    if "cpu" in payload:
        with contextlib.suppress(TypeError, ValueError):
            cpu = round(max(0.0, min(100.0, float(payload.get("cpu") or 0))), 1)
            fields["cpu"] = cpu
    revision = (payload.get("revision") or "").strip()[:40]
    if revision:
        fields["cfg_revision"] = revision
        fields["applied_at"] = iso()
    error = (payload.get("last_error") or "").strip()[:400]
    if "last_error" in payload:
        fields["last_error"] = error or None

    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE nodes SET {assignments} WHERE id = ?", (*fields.values(), node_id))

    # История метрик для графиков на дашборде (панель пишет то же самое для node_id = 0).
    if cpu is not None or "mem_used" in fields:
        add_metrics(
            node_id,
            cpu if cpu is not None else 0.0,
            fields.get("mem_used", 0),
            fields.get("mem_total", 0),
            fields.get("load1", 0.0),
        )


def touch_node(node_id: int, version: str | None = None) -> None:
    if version:
        db.run(
            "UPDATE nodes SET last_seen = ?, status = 'online', xray_version = ? WHERE id = ?",
            (iso(), version, node_id),
        )
    else:
        db.run(
            "UPDATE nodes SET last_seen = ?, status = 'online' WHERE id = ?",
            (iso(), node_id),
        )


def node_traffic_users(node_id: int) -> list[sqlite3.Row]:
    """Пользователи, которые должны быть на ноде (для генерации конфига)."""
    rows = db.all("SELECT * FROM users ORDER BY id")
    result: list[sqlite3.Row] = []
    for row in rows:
        node_ids = (row["node_ids"] or "").strip()
        if node_ids and str(node_id) not in [x.strip() for x in node_ids.split(",")]:
            continue
        if user_status(row) != "active":
            continue
        result.append(row)
    return result


# --------------------------------------------------------------------------
# Трафик
# --------------------------------------------------------------------------


def add_user_traffic(user_id: int, node_id: int, up: int, down: int) -> None:
    up = max(0, to_int(up))
    down = max(0, to_int(down))
    if up == 0 and down == 0:
        return
    day = today_str()
    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET up_bytes = up_bytes + ?, down_bytes = down_bytes + ?, "
            "last_online_at = ? WHERE id = ?",
            (up, down, iso(), user_id),
        )
        conn.execute(
            "INSERT INTO traffic(user_id, node_id, day, up, down) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id, node_id, day) DO UPDATE SET "
            "up = up + excluded.up, down = down + excluded.down",
            (user_id, node_id, day, up, down),
        )


def traffic_series(days: int = 14) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT day, SUM(up) AS up, SUM(down) AS down FROM traffic "
        "WHERE day >= ? GROUP BY day ORDER BY day",
        (today_str(-days + 1),),
    )
    by_day = {r["day"]: (to_int(r["up"]), to_int(r["down"])) for r in rows}
    series = []
    for offset in range(-days + 1, 1):
        day = today_str(offset)
        up, down = by_day.get(day, (0, 0))
        series.append({"day": day, "up": up, "down": down, "total": up + down})
    return series


def traffic_totals() -> dict[str, int]:
    row = db.one(
        "SELECT COALESCE(SUM(up_bytes),0) AS up, COALESCE(SUM(down_bytes),0) AS down FROM users"
    )
    today = db.one(
        "SELECT COALESCE(SUM(up),0) AS up, COALESCE(SUM(down),0) AS down "
        "FROM traffic WHERE day = ?",
        (today_str(),),
    )
    return {
        "up": to_int(row["up"]) if row else 0,
        "down": to_int(row["down"]) if row else 0,
        "today_up": to_int(today["up"]) if today else 0,
        "today_down": to_int(today["down"]) if today else 0,
    }


def purge_old_traffic(days: int) -> int:
    if days <= 0:
        return 0
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM traffic WHERE day < ?", (today_str(-days),))
        return cur.rowcount or 0


# --------------------------------------------------------------------------
# Журнал
# --------------------------------------------------------------------------


def audit(action: str, target: str = "", detail: Any = "", actor: str = "system", ip: str = "") -> None:
    db.run(
        "INSERT INTO audit(actor, action, target, detail, ip, created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, target, str(detail)[:500] if detail != "" else "", ip, iso()),
    )


def list_audit(limit: int = 60, offset: int = 0) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT * FROM audit ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    )
    return [dict(r) for r in rows]


def dashboard(base_url: str = "") -> dict[str, Any]:
    users = [serialize_user(r, base_url) for r in db.all("SELECT * FROM users")]
    nodes = list_nodes()
    counts = {"total": len(users), "active": 0, "disabled": 0, "expired": 0, "limited": 0}
    for user in users:
        counts[user["status"]] = counts.get(user["status"], 0) + 1
    nodes_online = sum(1 for n in nodes if n["status"] == "online")
    totals = traffic_totals()
    expiring = sorted(
        [u for u in users if u["status"] == "active" and u["days_left"] is not None and u["days_left"] <= 7],
        key=lambda u: u["days_left"],
    )[:5]
    top = sorted(users, key=lambda u: u["used_bytes"], reverse=True)[:5]
    series = traffic_series(14)
    traffic_30 = sum(
        to_int(r["total"])
        for r in (
            dict(x)
            for x in db.all(
                "SELECT day, SUM(up + down) AS total FROM traffic WHERE day >= ? GROUP BY day",
                (today_str(-29),),
            )
        )
    )
    return {
        "counts": counts,
        "nodes": {
            "total": len(nodes),
            "online": nodes_online,
            "offline": sum(1 for n in nodes if n["health"] == "offline"),
            "degraded": sum(1 for n in nodes if n["health"] == "degraded"),
            "items": nodes,
            "traffic": traffic_by_node(14),
        },
        "traffic": {
            "up": totals["up"],
            "down": totals["down"],
            "total": totals["up"] + totals["down"],
            "today": totals["today_up"] + totals["today_down"],
            "last_30_days": traffic_30,
            "series": series,
        },
        "expiring": expiring,
        "top": top,
        "audit": list_audit(8),
        "version": config.APP_VERSION,
    }


# --------------------------------------------------------------------------
# Группы клиентов
# --------------------------------------------------------------------------

GROUP_COLORS = (
    "#7c5cff", "#4f8cff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#2dd4bf",
)


def serialize_group(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    used = to_int(data.get("used_bytes"))
    return {
        "id": data["id"],
        "name": data["name"],
        "color": data.get("color") or GROUP_COLORS[0],
        "note": data.get("note") or "",
        "users_count": to_int(data.get("users_count")),
        "used_bytes": used,
        "used_human": human_size(used),
        "created_at": data.get("created_at") or "",
    }


def list_groups() -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT g.*, COUNT(u.id) AS users_count, "
        "COALESCE(SUM(u.up_bytes + u.down_bytes), 0) AS used_bytes "
        "FROM groups g LEFT JOIN users u ON u.group_id = g.id "
        "GROUP BY g.id ORDER BY g.name COLLATE NOCASE"
    )
    return [serialize_group(row) for row in rows]


def get_group(group_id: int) -> sqlite3.Row | None:
    return db.one("SELECT * FROM groups WHERE id = ?", (group_id,))


def create_group(payload: dict[str, Any]) -> int:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Укажите название группы")
    if len(name) > 64:
        raise ValueError("Название группы слишком длинное")
    if db.one("SELECT 1 FROM groups WHERE lower(name) = lower(?)", (name,)):
        raise ValueError("Группа с таким названием уже есть")
    return db.run(
        "INSERT INTO groups(name, color, note, created_at) VALUES(?,?,?,?)",
        (
            name,
            (payload.get("color") or "").strip() or GROUP_COLORS[0],
            (payload.get("note") or "").strip(),
            iso(),
        ),
    )


def update_group(group_id: int, payload: dict[str, Any]) -> None:
    row = get_group(group_id)
    if row is None:
        raise ValueError("Группа не найдена")
    fields: dict[str, Any] = {}
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            raise ValueError("Название группы не может быть пустым")
        other = db.one(
            "SELECT id FROM groups WHERE lower(name) = lower(?) AND id != ?",
            (name, group_id),
        )
        if other:
            raise ValueError("Группа с таким названием уже есть")
        fields["name"] = name
    if "color" in payload:
        fields["color"] = (payload["color"] or "").strip() or GROUP_COLORS[0]
    if "note" in payload:
        fields["note"] = (payload["note"] or "").strip()
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE groups SET {assignments} WHERE id = ?", (*fields.values(), group_id))


def delete_group(group_id: int) -> None:
    db.run("DELETE FROM groups WHERE id = ?", (group_id,))


# --------------------------------------------------------------------------
# Исходящие (outbounds)
# --------------------------------------------------------------------------

OUTBOUND_TYPES = ("direct", "block", "socks", "http", "wireguard", "shadowsocks", "trojan")


def _slug_tag(name: str, fallback: str = "outbound") -> str:
    letters = [ch.lower() if ch.isalnum() else "-" for ch in (name or "")]
    slug = "".join(letters).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:32] or fallback


def serialize_outbound(row: sqlite3.Row | dict[str, Any], with_secrets: bool = False) -> dict[str, Any]:
    data = dict(row)
    password = data.get("password") or ""
    return {
        "id": data["id"],
        "name": data["name"],
        "tag": data.get("tag") or _slug_tag(data["name"]),
        "type": data.get("type") or "direct",
        "address": data.get("address") or "",
        "port": to_int(data.get("port")),
        "username": data.get("username") or "",
        "password": password if with_secrets else ("•" * 8 if password else ""),
        "sni": data.get("sni") or "",
        "enabled": bool(to_int(data.get("enabled"))),
        "sort": to_int(data.get("sort")),
        "created_at": data.get("created_at") or "",
        "updated_at": data.get("updated_at") or "",
    }


def list_outbounds(with_secrets: bool = False) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM outbounds ORDER BY sort, id")
    return [serialize_outbound(row, with_secrets) for row in rows]


def get_outbound(outbound_id: int) -> sqlite3.Row | None:
    return db.one("SELECT * FROM outbounds WHERE id = ?", (outbound_id,))


def create_outbound(payload: dict[str, Any]) -> int:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Укажите название исходящего")
    kind = (payload.get("type") or "direct").strip().lower()
    if kind not in OUTBOUND_TYPES:
        raise ValueError("Неизвестный тип исходящего")
    stamp = iso()
    return db.run(
        "INSERT INTO outbounds(name, tag, type, address, port, username, password, sni, "
        "enabled, sort, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            name,
            (payload.get("tag") or "").strip() or _slug_tag(name),
            kind,
            (payload.get("address") or "").strip(),
            to_int(payload.get("port")),
            (payload.get("username") or "").strip(),
            (payload.get("password") or "").strip(),
            (payload.get("sni") or "").strip(),
            1 if to_bool(payload.get("enabled", True)) else 0,
            to_int(payload.get("sort", 100)),
            stamp,
            stamp,
        ),
    )


def update_outbound(outbound_id: int, payload: dict[str, Any]) -> None:
    row = get_outbound(outbound_id)
    if row is None:
        raise ValueError("Исходящий не найден")
    fields: dict[str, Any] = {}
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            raise ValueError("Название не может быть пустым")
        fields["name"] = name
    if "tag" in payload:
        fields["tag"] = (payload["tag"] or "").strip() or _slug_tag(
            fields.get("name") or dict(row)["name"]
        )
    if "type" in payload:
        kind = (payload["type"] or "").strip().lower()
        if kind not in OUTBOUND_TYPES:
            raise ValueError("Неизвестный тип исходящего")
        fields["type"] = kind
    for key in ("address", "username", "sni"):
        if key in payload:
            fields[key] = (payload[key] or "").strip()
    if "password" in payload:
        fields["password"] = (payload["password"] or "").strip()
    if "port" in payload:
        fields["port"] = to_int(payload["port"])
    if "sort" in payload:
        fields["sort"] = to_int(payload["sort"])
    if "enabled" in payload:
        fields["enabled"] = 1 if to_bool(payload["enabled"]) else 0
    if not fields:
        return
    fields["updated_at"] = iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE outbounds SET {assignments} WHERE id = ?", (*fields.values(), outbound_id))


def delete_outbound(outbound_id: int) -> None:
    db.run("DELETE FROM outbounds WHERE id = ?", (outbound_id,))


# --------------------------------------------------------------------------
# Команды агентам нод (перезапуск Xray и проверка конфига)
# --------------------------------------------------------------------------

NODE_COMMANDS: dict[str, str] = {
    "restart_xray": "Перезапустить Xray",
    "test_config": "Проверить конфиг через xray -test",
    "restart_agent": "Перезапустить агент",
}
MAX_PENDING_COMMANDS = 5


def create_node_command(node_id: int, command: str, actor: str = "") -> int:
    if command not in NODE_COMMANDS:
        raise ValueError("Неизвестная команда для ноды")
    stamp = iso()
    command_id = db.run(
        "INSERT INTO node_commands(node_id, command, status, created_by, created_at) "
        "VALUES(?, ?, 'pending', ?, ?)",
        (node_id, command, actor, stamp),
    )
    return int(command_id)


def node_commands_queue(node_id: int, limit: int = MAX_PENDING_COMMANDS) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT * FROM node_commands WHERE node_id = ? AND status = 'pending' "
        "ORDER BY id ASC LIMIT ?",
        (node_id, limit),
    )
    items = [dict(row) for row in rows]
    if items:
        placeholders = ",".join("?" for _ in items)
        db.run(
            f"UPDATE node_commands SET status = 'running' WHERE id IN ({placeholders})",
            tuple(item["id"] for item in items),
        )
    return items


COMMAND_OK_STATUSES = {"done", "ok", "success", "completed", "0"}


def finish_node_command(command_id: int, status: str, result: str = "") -> None:
    """Зафиксировать результат команды. Агент присылает done/error, но панель
    принимает и человеческие варианты (ok/success), чтобы не писать ложную ошибку."""
    normalized = "done" if str(status).strip().lower() in COMMAND_OK_STATUSES else "error"
    db.run(
        "UPDATE node_commands SET status = ?, result = ?, finished_at = ? WHERE id = ?",
        (normalized, str(result)[:400], iso(), command_id),
    )


def list_node_commands(node_id: int, limit: int = 15) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT * FROM node_commands WHERE node_id = ? ORDER BY id DESC LIMIT ?",
        (node_id, limit),
    )
    items = []
    for row in rows:
        item = dict(row)
        item["title"] = NODE_COMMANDS.get(item["command"], item["command"])
        items.append(item)
    return items


# --------------------------------------------------------------------------
# Метрики железа: панель (node_id = 0) и ноды
# --------------------------------------------------------------------------

PANEL_METRICS_ID = 0


def add_metrics(node_id: int, cpu: float, mem_used: int, mem_total: int, load1: float) -> None:
    db.run(
        "INSERT INTO metrics(node_id, ts, cpu, mem_used, mem_total, load1) VALUES(?,?,?,?,?,?)",
        (node_id, int(time.time()), round(float(cpu or 0), 1), max(0, to_int(mem_used)),
         max(0, to_int(mem_total)), round(float(load1 or 0), 2)),
    )


def metrics_series(node_id: int, minutes: int = 60, limit: int = 720) -> list[dict[str, Any]]:
    since = int(time.time()) - max(1, minutes) * 60
    rows = db.all(
        "SELECT ts, cpu, mem_used, mem_total, load1 FROM metrics "
        "WHERE node_id = ? AND ts >= ? ORDER BY ts DESC LIMIT ?",
        (node_id, since, limit),
    )
    return [dict(row) for row in reversed(rows)]


def prune_metrics(hours: int = 48) -> int:
    cutoff = int(time.time()) - max(1, hours) * 3600
    return int(db.run("DELETE FROM metrics WHERE ts < ?", (cutoff,)))


def latest_metrics(node_id: int) -> dict[str, Any] | None:
    row = db.one(
        "SELECT ts, cpu, mem_used, mem_total, load1 FROM metrics "
        "WHERE node_id = ? ORDER BY ts DESC, rowid DESC LIMIT 1",
        (node_id,),
    )
    return dict(row) if row else None
