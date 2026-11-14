"""Доступ к данным панели: пользователи, ноды, трафик, журнал."""

from __future__ import annotations

import datetime as dt
import sqlite3
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
    "note",
    "sort",
)

TRANSPORTS = ("tcp", "ws", "grpc", "xhttp", "h2")
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
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append(
            "(lower(username) LIKE ? OR lower(coalesce(email,'')) LIKE ? "
            "OR lower(coalesce(note,'')) LIKE ? OR uuid LIKE ?)"
        )
        pattern = f"%{q.strip().lower()}%"
        params += [pattern, pattern, pattern, f"%{q.strip()}%"]
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.all(
        f"SELECT * FROM users {clause} ORDER BY id DESC", params
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
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,))


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
    return db.run(
        """INSERT INTO users(
            username, email, uuid, sub_token, flow, limit_bytes,
            expires_at, enabled, note, device_limit, node_ids, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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


def serialize_node(row: sqlite3.Row | dict[str, Any], with_secrets: bool = False) -> dict[str, Any]:
    data = dict(row)
    node = {
        "id": data["id"],
        "name": data["name"],
        "address": data["address"],
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
        "status": node_status(data),
        "last_seen": data.get("last_seen") or "",
        "xray_version": data.get("xray_version") or "",
        "up_bytes": to_int(data.get("up_bytes")),
        "down_bytes": to_int(data.get("down_bytes")),
        "note": data.get("note") or "",
        "sort": to_int(data.get("sort")),
        "created_at": data.get("created_at") or "",
    }
    if with_secrets:
        node["private_key"] = data.get("private_key") or ""
        node["agent_token"] = data.get("agent_token") or ""
    return node


def list_nodes(with_secrets: bool = False) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM nodes ORDER BY sort, id")
    return [serialize_node(r, with_secrets) for r in rows]


def get_node(node_id: int) -> sqlite3.Row | None:
    return db.one("SELECT * FROM nodes WHERE id = ?", (node_id,))


def get_node_by_token(agent_token: str) -> sqlite3.Row | None:
    return db.one("SELECT * FROM nodes WHERE agent_token = ?", ((agent_token or "").strip(),))


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
            name, address, port, protocol, transport, security, sni, fingerprint,
            private_key, public_key, short_id, dest, path, service_name, flow,
            alpn, cert_file, key_file, enabled, note, sort, agent_token, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            address,
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
        if key in ("enabled",):
            fields[key] = 1 if to_bool(payload[key]) else 0
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


def delete_node(node_id: int) -> None:
    db.run("DELETE FROM nodes WHERE id = ?", (node_id,))
    db.run("DELETE FROM traffic WHERE node_id = ?", (node_id,))


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
        "nodes": {"total": len(nodes), "online": nodes_online, "items": nodes},
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
