"""JSON API панели."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from . import auth, config, db, qr, repo, xray
from .server import (
    ApiError,
    Request,
    Response,
    delete,
    get,
    json_response,
    patch,
    post,
)
from .utils import iso, now, sha256, to_bool, to_int

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _settings_label() -> dict[str, str]:
    settings = db.get_settings()
    return {
        "panel_title": settings.get("panel_title", "DF_Xray"),
        "panel_subtitle": settings.get("panel_subtitle", "Panel"),
        "footer_note": settings.get("footer_note", ""),
    }


def _user_or_404(user_id: int):
    row = repo.get_user(to_int(user_id))
    if row is None:
        raise ApiError(404, "Пользователь не найден")
    return row


def _node_or_404(node_id: int):
    row = repo.get_node(to_int(node_id))
    if row is None:
        raise ApiError(404, "Нода не найдена")
    return row


def _user_payload(req: Request, row) -> dict[str, Any]:
    base = req.base_url()
    data = repo.serialize_user(row, base)
    nodes = [n for n in repo.list_nodes() if n["enabled"]]
    settings = db.get_settings()
    links = xray.build_links(row, nodes, settings.get("panel_title", "DF_Xray"))
    for link in links:
        if base:
            link["qr_url"] = (
                f"{base}/api/users/{row['id']}/qr.svg?node_id={link['node_id']}"
            )
    data["links"] = links
    return data


def _audit(req: Request, action: str, target: str = "", detail: Any = "") -> None:
    actor = req.admin["username"] if req.admin else "system"
    repo.audit(action, target, detail, actor=actor, ip=req.ip)


# --------------------------------------------------------------------------
# Авторизация
# --------------------------------------------------------------------------


@post("/api/auth/login", auth_required=False)
def login(req: Request) -> Response:
    ip = req.ip
    if not auth.login_allowed(ip):
        raise ApiError(429, "Слишком много попыток входа. Попробуйте позже.")
    payload = req.json()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    row = auth.find_admin(username)
    if row is None or not auth.verify_password(password, row["password_hash"]):
        auth.record_failed_login(ip)
        repo.audit("auth.login_failed", username, "неверный логин или пароль", ip=ip)
        raise ApiError(401, "Неверное имя пользователя или пароль")
    auth.clear_login_attempts(ip)
    raw = auth.create_session(row["id"], ip, req.header("user-agent"))
    resp = json_response(
        {
            "admin": {
                "id": row["id"],
                "username": row["username"],
                "last_login_at": iso(),
            },
            "bootstrap_password": db.get_setting("password_changed") != "1",
        }
    )
    resp.set_cookie(
        config.SESSION_COOKIE,
        raw,
        max_age=config.SESSION_TTL_HOURS * 3600,
        secure=req.scheme == "https",
    )
    repo.audit("auth.login", row["username"], ip=ip)
    return resp


@post("/api/auth/logout")
def logout(req: Request) -> Response:
    auth.delete_session(req.cookies.get(config.SESSION_COOKIE))
    _audit(req, "auth.logout", req.admin["username"])
    resp = json_response({"ok": True})
    resp.set_cookie(config.SESSION_COOKIE, "", max_age=0)
    return resp


@get("/api/me")
def me(req: Request) -> Response:
    settings = db.get_settings()
    return json_response(
        {
            "admin": req.admin,
            "panel": _settings_label(),
            "bootstrap_password": settings.get("password_changed") != "1",
            "version": config.APP_VERSION,
            "api_version": config.API_VERSION,
            "base_url": req.base_url(),
        }
    )


@post("/api/account/password")
def change_password(req: Request) -> Response:
    payload = req.json()
    current = payload.get("current_password") or ""
    new = payload.get("new_password") or ""
    row = db.one("SELECT * FROM admins WHERE id = ?", (req.admin["id"],))
    if row is None or not auth.verify_password(current, row["password_hash"]):
        raise ApiError(400, "Текущий пароль указан неверно")
    if len(new) < 8:
        raise ApiError(400, "Новый пароль должен быть не короче 8 символов")
    auth.set_password(req.admin["id"], new)
    _audit(req, "auth.password_change", req.admin["username"])
    raw = auth.create_session(req.admin["id"], req.ip, req.header("user-agent"))
    resp = json_response({"ok": True})
    resp.set_cookie(
        config.SESSION_COOKIE,
        raw,
        max_age=config.SESSION_TTL_HOURS * 3600,
        secure=req.scheme == "https",
    )
    return resp


@post("/api/account/sessions/revoke")
def revoke_sessions(req: Request) -> Response:
    removed = auth.delete_other_sessions(
        req.admin["id"], req.cookies.get(config.SESSION_COOKIE)
    )
    _audit(req, "auth.sessions_revoke", str(removed))
    return json_response({"ok": True, "removed": removed})


# --------------------------------------------------------------------------
# Дашборд
# --------------------------------------------------------------------------


@get("/api/dashboard")
def dashboard(req: Request) -> Response:
    data = repo.dashboard(req.base_url())
    data["panel"] = _settings_label()
    data["admin"] = req.admin
    data["nodes"]["base_url"] = req.base_url()
    return json_response(data)


# --------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------


@get("/api/users")
def users_index(req: Request) -> Response:
    base = req.base_url()
    items, total = repo.list_users(
        q=req.q("q"),
        status=req.q("status", "all"),
        sort=req.q("sort", "created_desc"),
        limit=req.q_int("limit", 500),
        offset=req.q_int("offset", 0),
        base_url=base,
    )
    all_items, _ = repo.list_users(limit=100000, base_url=base)
    summary = {"total": len(all_items)}
    for status in ("active", "disabled", "expired", "limited"):
        summary[status] = sum(1 for u in all_items if u["status"] == status)
    return json_response({"items": items, "total": total, "summary": summary})


@post("/api/users")
def users_create(req: Request) -> Response:
    payload = req.json()
    settings = db.get_settings()
    if payload.get("days") in (None, ""):
        payload["days"] = settings.get("default_days", "30")
    if payload.get("limit_gb") in (None, ""):
        payload["limit_gb"] = settings.get("default_limit_gb", "0")
    if payload.get("device_limit") in (None, ""):
        payload["device_limit"] = settings.get("default_device_limit", "0")
    try:
        user_id = repo.create_user(payload)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = _user_or_404(user_id)
    _audit(req, "user.create", row["username"], f"id={user_id}")
    return json_response(_user_payload(req, row), status=201)


@get("/api/users/export")
def users_export(req: Request) -> Response:
    items, _ = repo.list_users(limit=100000, base_url=req.base_url())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "username",
            "email",
            "uuid",
            "status",
            "used_gb",
            "limit_gb",
            "expires_at",
            "sub_url",
            "note",
            "created_at",
        ]
    )
    for user in items:
        writer.writerow(
            [
                user["username"],
                user["email"],
                user["uuid"],
                user["status"],
                round(user["used_bytes"] / 1024 ** 3, 3),
                user["limit_gb"],
                user["expires_at"],
                user["sub_url"],
                user["note"],
                user["created_at"],
            ]
        )
    filename = f"dfxray-users-{now().strftime('%Y%m%d')}.csv"
    return Response(
        "\ufeff" + buffer.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@get(r"/api/users/(?P<user_id>\d+)")
def users_show(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    return json_response(_user_payload(req, row))


@patch(r"/api/users/(?P<user_id>\d+)")
def users_update(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    try:
        repo.update_user(row["id"], req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    updated = _user_or_404(row["id"])
    _audit(req, "user.update", updated["username"], f"id={row['id']}")
    return json_response(_user_payload(req, updated))


@delete(r"/api/users/(?P<user_id>\d+)")
def users_delete(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    repo.delete_user(row["id"])
    _audit(req, "user.delete", row["username"], f"id={row['id']}")
    return json_response({"ok": True})


@post(r"/api/users/(?P<user_id>\d+)/action")
def users_action(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    payload = req.json()
    action = (payload.get("action") or "").strip()
    if action == "enable":
        repo.update_user(row["id"], {"enabled": True})
    elif action == "disable":
        repo.update_user(row["id"], {"enabled": False})
    elif action == "reset_traffic":
        repo.reset_traffic(row["id"])
    elif action == "rotate_uuid":
        repo.rotate_uuid(row["id"])
    elif action == "rotate_sub":
        repo.rotate_sub_token(row["id"])
    elif action == "extend":
        days = to_int(payload.get("value"), 30)
        repo.extend_user(row["id"], days)
    elif action == "set_limit":
        repo.update_user(row["id"], {"limit_gb": payload.get("value", 0)})
    else:
        raise ApiError(400, "Неизвестное действие")
    updated = _user_or_404(row["id"])
    _audit(req, f"user.{action}", updated["username"], payload.get("value", ""))
    return json_response(_user_payload(req, updated))


@get(r"/api/users/(?P<user_id>\d+)/qr")
@get(r"/api/users/(?P<user_id>\d+)/qr\.svg")
def users_qr(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    node_id = req.q_int("node_id", 0)
    settings = db.get_settings()
    nodes = [n for n in repo.list_nodes() if n["enabled"]]
    if node_id:
        nodes = [n for n in nodes if n["id"] == node_id]
    if not nodes:
        raise ApiError(404, "Нет доступных нод для этого пользователя")
    link = xray.build_link(nodes[0], row, settings.get("panel_title", "DF_Xray"))
    fmt = req.q("format", "svg").lower()
    if fmt == "png":
        return Response(
            qr.png(link, scale=req.q_int("scale", 8), border=3),
            content_type="image/png",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        qr.svg(link, module_px=8, border=3, title=row["username"]),
        content_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@get(r"/api/users/(?P<user_id>\d+)/subscription")
def users_subscription(req: Request) -> Response:
    row = _user_or_404(req.params["user_id"])
    settings = db.get_settings()
    nodes = [n for n in repo.list_nodes() if n["enabled"]]
    links = xray.build_links(row, nodes, settings.get("panel_title", "DF_Xray"))
    base = req.base_url()
    payload = {
        "user": repo.serialize_user(row, base),
        "links": links,
        "text": xray.subscription_text([item["link"] for item in links]),
        "sub_url": f"{base}/sub/{row['sub_token']}",
        "page_url": f"{base}/sub/{row['sub_token']}/page",
        "qr_svg_url": f"{base}/api/users/{row['id']}/qr.svg",
    }
    return json_response(payload)


# --------------------------------------------------------------------------
# Ноды
# --------------------------------------------------------------------------


@get("/api/nodes")
def nodes_index(req: Request) -> Response:
    nodes = repo.list_nodes()
    for node in nodes:
        node["users_count"] = len(repo.node_traffic_users(node["id"]))
    total_up = sum(n["up_bytes"] for n in nodes)
    total_down = sum(n["down_bytes"] for n in nodes)
    return json_response(
        {
            "items": nodes,
            "summary": {
                "total": len(nodes),
                "online": sum(1 for n in nodes if n["status"] == "online"),
                "up_bytes": total_up,
                "down_bytes": total_down,
            },
            "transports": list(repo.TRANSPORTS),
            "securities": list(repo.SECURITIES),
            "protocols": list(repo.PROTOCOLS),
        }
    )


@post("/api/nodes")
def nodes_create(req: Request) -> Response:
    try:
        node_id = repo.create_node(req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = _node_or_404(node_id)
    _audit(req, "node.create", row["name"], f"id={node_id}")
    return json_response(repo.serialize_node(row, with_secrets=True), status=201)


@get(r"/api/nodes/(?P<node_id>\d+)")
def nodes_show(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    data = repo.serialize_node(row, with_secrets=True)
    data["config"] = xray.build_config(row, repo.node_traffic_users(row["id"]), db.get_settings())
    data["users_count"] = len(repo.node_traffic_users(row["id"]))
    data["base_url"] = req.base_url()
    return json_response(data)


@patch(r"/api/nodes/(?P<node_id>\d+)")
def nodes_update(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    try:
        repo.update_node(row["id"], req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    updated = _node_or_404(row["id"])
    _audit(req, "node.update", updated["name"], f"id={row['id']}")
    return json_response(repo.serialize_node(updated, with_secrets=True))


@delete(r"/api/nodes/(?P<node_id>\d+)")
def nodes_delete(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    repo.delete_node(row["id"])
    _audit(req, "node.delete", row["name"], f"id={row['id']}")
    return json_response({"ok": True})


@post(r"/api/nodes/(?P<node_id>\d+)/probe")
def nodes_probe(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    result = xray.probe(row["address"], row["port"])
    if result["ok"]:
        repo.touch_node(row["id"])
    return json_response(result)


@get(r"/api/nodes/(?P<node_id>\d+)/config")
def nodes_config(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    users = repo.node_traffic_users(row["id"])
    data = xray.build_config(row, users, db.get_settings())
    body = json.dumps(data, ensure_ascii=False, indent=2)
    headers = {}
    if req.q("download") == "1":
        headers["Content-Disposition"] = f'attachment; filename="xray-{row["id"]}.json"'
    return Response(body, content_type="application/json; charset=utf-8", headers=headers)


@post(r"/api/nodes/(?P<node_id>\d+)/reality-keys")
def nodes_reality_keys(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    try:
        private_key, public_key = xray.generate_reality_keypair()
    except RuntimeError as exc:
        raise ApiError(400, str(exc)) from exc
    repo.update_node(row["id"], {"private_key": private_key, "public_key": public_key})
    _audit(req, "node.reality_keys", row["name"])
    return json_response({"private_key": private_key, "public_key": public_key})


@post(r"/api/nodes/(?P<node_id>\d+)/rotate-token")
def nodes_rotate_token(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    from .utils import token as make_token

    value = make_token(20)
    repo.update_node(row["id"], {})  # ensure node exists / timestamps
    db.run("UPDATE nodes SET agent_token = ? WHERE id = ?", (value, row["id"]))
    _audit(req, "node.rotate_token", row["name"])
    return json_response({"agent_token": value})


# --------------------------------------------------------------------------
# Подписки, настройки, журнал
# --------------------------------------------------------------------------


@get("/api/subscriptions")
def subscriptions(req: Request) -> Response:
    base = req.base_url()
    users, _ = repo.list_users(limit=100000, base_url=base)
    settings = db.get_settings()
    return json_response(
        {
            "items": users,
            "base_url": base,
            "settings": {
                "sub_title": settings.get("sub_title", ""),
                "sub_support_url": settings.get("sub_support_url", ""),
                "sub_update_interval": to_int(settings.get("sub_update_interval"), 12),
                "sub_page_enabled": to_bool(settings.get("sub_page_enabled")),
                "sub_show_nodes": to_bool(settings.get("sub_show_nodes")),
            },
        }
    )


BOOL_SETTINGS = (
    "sub_page_enabled",
    "sub_show_nodes",
    "block_bittorrent",
    "block_ads",
    "block_private",
    "route_ru_direct",
)
INT_SETTINGS = (
    "sub_update_interval",
    "default_days",
    "default_device_limit",
    "traffic_retention_days",
)


@get("/api/settings")
def settings_get(req: Request) -> Response:
    settings = db.get_settings()
    for key in BOOL_SETTINGS:
        settings[key] = to_bool(settings.get(key))
    for key in INT_SETTINGS:
        settings[key] = to_int(settings.get(key))
    settings["base_url"] = req.base_url()
    settings["version"] = config.APP_VERSION
    settings["node_offline_after"] = config.NODE_OFFLINE_AFTER_SECONDS
    return json_response(settings)


SETTING_TYPES = {
    "panel_title": str,
    "panel_subtitle": str,
    "public_base_url": str,
    "sub_title": str,
    "sub_support_url": str,
    "sub_update_interval": int,
    "sub_page_enabled": bool,
    "sub_show_nodes": bool,
    "block_bittorrent": bool,
    "block_ads": bool,
    "block_private": bool,
    "route_ru_direct": bool,
    "dns_preset": str,
    "default_days": int,
    "default_limit_gb": str,
    "default_device_limit": int,
    "traffic_retention_days": int,
    "footer_note": str,
}


@patch("/api/settings")
def settings_update(req: Request) -> Response:
    payload = req.json()
    values: dict[str, Any] = {}
    for key, caster in SETTING_TYPES.items():
        if key not in payload:
            continue
        value = payload[key]
        if caster is bool:
            values[key] = "1" if to_bool(value) else "0"
        elif caster is int:
            values[key] = str(to_int(value))
        else:
            if key == "public_base_url":
                value = (value or "").strip().rstrip("/")
                if value and not value.startswith(("http://", "https://")):
                    raise ApiError(400, "Публичный адрес должен начинаться с http:// или https://")
            values[key] = (value or "").strip() if isinstance(value, str) else str(value)
    if "dns_preset" in values and values["dns_preset"] not in xray.DNS_PRESETS:
        raise ApiError(400, "Неизвестный DNS-пресет")
    if not values:
        return json_response({"ok": True, "updated": 0})
    db.update_settings(values)
    _audit(req, "settings.update", ", ".join(values.keys()))
    return json_response({"ok": True, "updated": len(values)})


@get("/api/audit")
def audit_index(req: Request) -> Response:
    limit = min(req.q_int("limit", 60), 300)
    offset = req.q_int("offset", 0)
    return json_response(
        {
            "items": repo.list_audit(limit, offset),
            "total": db.scalar("SELECT COUNT(*) FROM audit"),
        }
    )


@get("/api/maintenance/backup")
def maintenance_backup(req: Request) -> Response:
    """Скачать консистентную копию SQLite-базы."""
    import sqlite3

    source = sqlite3.connect(config.DB_PATH, timeout=20)
    try:
        try:
            payload = source.serialize()
        except AttributeError:  # Python < 3.11
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                target = sqlite3.connect(tmp.name)
                with target:
                    source.backup(target)
                target.close()
            with open(tmp.name, "rb") as fh:
                payload = fh.read()
            import os

            os.unlink(tmp.name)
    finally:
        source.close()
    _audit(req, "maintenance.backup", f"{len(payload)} байт")
    filename = f"dfxray-backup-{now().strftime('%Y%m%d-%H%M')}.db"
    return Response(
        payload,
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@post("/api/maintenance/purge-traffic")
def purge_traffic(req: Request) -> Response:
    settings = db.get_settings()
    days = to_int(settings.get("traffic_retention_days"), 90)
    removed = repo.purge_old_traffic(days)
    _audit(req, "maintenance.purge_traffic", str(removed), f"days={days}")
    return json_response({"ok": True, "removed": removed})


# --------------------------------------------------------------------------
# API для агента ноды
# --------------------------------------------------------------------------


def _agent_node(req: Request):
    token = req.header("x-node-token") or req.q("token") or (req.json().get("token") if req.body else "")
    node = repo.get_node_by_token(str(token or ""))
    if node is None:
        raise ApiError(401, "Неизвестный токен ноды")
    return node


def _config_revision(node_id: int, users) -> str:
    payload = "|".join(
        f"{u['id']}:{u['uuid']}:{u['flow'] or ''}:{u['device_limit']}" for u in users
    )
    return sha256(f"{node_id}:{payload}")[:16]


@get("/api/agent/config", auth_required=False)
def agent_config(req: Request) -> Response:
    node = _agent_node(req)
    users = repo.node_traffic_users(node["id"])
    config_data = xray.build_config(node, users, db.get_settings())
    repo.touch_node(node["id"])
    return json_response(
        {
            "node": {
                "id": node["id"],
                "name": node["name"],
                "transport": node["transport"],
                "security": node["security"],
                "protocol": node["protocol"],
                "port": node["port"],
            },
            "revision": _config_revision(node["id"], users),
            "users": len(users),
            "api_port": xray.API_PORT,
            "poll_interval": config.AGENT_POLL_SECONDS,
            "config": config_data,
        }
    )


@post("/api/agent/heartbeat", auth_required=False)
def agent_heartbeat(req: Request) -> Response:
    node = _agent_node(req)
    payload = req.json()
    version = (payload.get("xray_version") or "").strip()[:40]
    repo.touch_node(node["id"], version or None)
    return json_response({"ok": True, "ts": iso(), "poll_interval": config.AGENT_POLL_SECONDS})


@post("/api/agent/report", auth_required=False)
def agent_report(req: Request) -> Response:
    node = _agent_node(req)
    payload = req.json()
    stats = payload.get("stats") or {}
    users_stats = stats.get("users") or {}
    reported = 0
    disabled: list[str] = []
    for email, values in users_stats.items():
        if not isinstance(values, dict):
            continue
        row = db.one("SELECT * FROM users WHERE username = ?", (str(email),))
        if row is None:
            continue
        up = to_int(values.get("up"))
        down = to_int(values.get("down"))
        if up <= 0 and down <= 0:
            continue
        repo.add_user_traffic(row["id"], node["id"], up, down)
        reported += 1
        fresh = db.one("SELECT * FROM users WHERE id = ?", (row["id"],))
        if fresh is not None and repo.user_status(fresh) != "active":
            disabled.append(fresh["username"])
    node_up = to_int(stats.get("node", {}).get("up")) if isinstance(stats, dict) else 0
    node_down = to_int(stats.get("node", {}).get("down")) if isinstance(stats, dict) else 0
    if node_up or node_down:
        db.run(
            "UPDATE nodes SET up_bytes = up_bytes + ?, down_bytes = down_bytes + ? WHERE id = ?",
            (node_up, node_down, node["id"]),
        )
    repo.touch_node(node["id"], (payload.get("xray_version") or "").strip()[:40] or None)
    users = repo.node_traffic_users(node["id"])
    return json_response(
        {
            "ok": True,
            "reported": reported,
            "blocked": disabled,
            "revision": _config_revision(node["id"], users),
            "users": len(users),
            "poll_interval": config.AGENT_POLL_SECONDS,
        }
    )
