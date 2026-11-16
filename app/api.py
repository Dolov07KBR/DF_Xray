"""JSON API панели."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from . import (
    auth,
    config,
    db,
    latency,
    nodecfg,
    nodeinstall,
    notify,
    qr,
    reality,
    repo,
    sni,
    sysinfo,
    tgbot,
    updates,
    xray,
    xraycheck,
)
from .server import (
    ROUTES,
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
    if links and settings.get("sub_sort_by_latency", "1") == "1":
        latencies = latency.measure([n for n in nodes if not n["drain"]])
        links = latency.sort_links(links, latencies)
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
    challenge = str(payload.get("challenge") or "")
    code = str(payload.get("code") or "")
    row = auth.find_admin(username)
    # Второй шаг 2FA: действующий challenge уже подтверждает, что пароль верный.
    resumed = bool(row) and bool(challenge) and auth.resolve_challenge(challenge) == row["id"]
    if not resumed and (row is None or not auth.verify_password(password, row["password_hash"])):
        auth.record_failed_login(ip)
        repo.audit("auth.login_failed", username, "неверный логин или пароль", ip=ip)
        raise ApiError(401, "Неверное имя пользователя или пароль")
    if auth.totp_status(row["id"])["enabled"]:
        if not code:
            raw = auth.create_challenge(row["id"])
            return json_response(
                {"totp_required": True, "challenge": raw, "username": row["username"]}
            )
        if not resumed:
            auth.record_failed_login(ip)
            repo.audit("auth.2fa_failed", username, "истёк challenge", ip=ip)
            raise ApiError(401, "Время на ввод кода истекло — войдите заново")
        if not auth.check_second_factor(row["id"], code):
            auth.record_failed_login(ip)
            repo.audit("auth.2fa_failed", username, "неверный код", ip=ip)
            raise ApiError(401, "Неверный код двухфакторной аутентификации")
        auth.drop_challenge(challenge)
    auth.clear_login_attempts(ip)
    raw = auth.create_session(row["id"], ip, req.header("user-agent"))
    resp = json_response(
        {
            "admin": {
                "id": row["id"],
                "username": row["username"],
                "last_login_at": iso(),
                "totp": auth.totp_status(row["id"])["enabled"],
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


def _metrics_payload(node_id: int, minutes: int = 60) -> dict[str, Any]:
    items = repo.metrics_series(node_id, minutes)
    series = []
    for item in items:
        total = to_int(item.get("mem_total"))
        used = to_int(item.get("mem_used"))
        series.append(
            {
                "ts": item["ts"],
                "cpu": round(float(item.get("cpu") or 0), 1),
                "mem": round(used * 100 / total, 1) if total else 0.0,
                "mem_used": used,
                "mem_total": total,
                "load1": round(float(item.get("load1") or 0), 2),
            }
        )
    return {"node_id": node_id, "minutes": minutes, "series": series,
            "current": series[-1] if series else None}


@get("/api/metrics")
def metrics_index(req: Request) -> Response:
    node_id = to_int(req.q("node_id"), repo.PANEL_METRICS_ID)
    minutes = max(5, min(to_int(req.q("minutes"), 60), 24 * 60))
    data = _metrics_payload(node_id, minutes)
    if node_id == repo.PANEL_METRICS_ID:
        data["host"] = sysinfo.host_snapshot()
    else:
        node = repo.get_node(node_id)
        if node is None:
            raise ApiError(404, "Нода не найдена")
        data["host"] = {
            "name": node["name"],
            "cpu": (repo.latest_metrics(node_id) or {}).get("cpu", 0.0),
            "mem_used": to_int(node["mem_used"]),
            "mem_total": to_int(node["mem_total"]),
            "load1": node["load1"],
            "uptime": to_int(node["uptime_seconds"]),
        }
    return json_response(data)


@get("/api/dashboard")
def dashboard(req: Request) -> Response:
    data = repo.dashboard(req.base_url())
    data["panel"] = _settings_label()
    data["admin"] = req.admin
    data["nodes"]["base_url"] = req.base_url()
    data["system"] = _metrics_payload(repo.PANEL_METRICS_ID, 60)
    data["system"]["host"] = sysinfo.host_snapshot()
    data["nodes"]["metrics"] = {
        str(node["id"]): repo.latest_metrics(node["id"]) for node in data["nodes"]["items"]
    }
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
        group_id=req.q_int("group_id", 0),
    )
    all_items, _ = repo.list_users(limit=100000, base_url=base)
    summary = {"total": len(all_items)}
    for status in ("active", "disabled", "expired", "limited"):
        summary[status] = sum(1 for u in all_items if u["status"] == status)
    return json_response(
        {
            "items": items,
            "total": total,
            "summary": summary,
            "groups": repo.list_groups(),
        }
    )


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
    elif action == "set_group":
        repo.update_user(row["id"], {"group_id": payload.get("value", 0)})
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
    down = sum(1 for n in nodes if n["health"] == "offline")
    degraded = sum(1 for n in nodes if n["health"] == "degraded")
    return json_response(
        {
            "items": nodes,
            "summary": {
                "total": len(nodes),
                "online": sum(1 for n in nodes if n["status"] == "online"),
                "offline": down,
                "degraded": degraded,
                "up_bytes": total_up,
                "down_bytes": total_down,
            },
            "transports": list(repo.TRANSPORTS),
            "securities": list(repo.SECURITIES),
            "protocols": list(repo.PROTOCOLS),
        }
    )


def _node_payload(payload: dict[str, Any], *, fill: bool = True) -> dict[str, Any]:
    """Применить пресет автонастройки, достроить поля и проверить совместимость."""
    data = dict(payload)
    preset_id = str(data.pop("preset", "") or "").strip()
    if preset_id:
        base = nodecfg.preset(preset_id)
        for key, value in base.items():
            if key in ("id", "title", "hint", "badge"):
                continue
            data.setdefault(key, value)
    if not fill:
        return data
    prepared = nodecfg.decorate(data)
    nodecfg.require_sni(prepared)
    nodecfg.validate(prepared)
    prepared = _auto_node_secrets(prepared)
    return prepared


def _auto_node_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """Достроить секреты ноды, чтобы ничего не приходилось вводить руками.

    Reality: пара X25519 и shortId считаются на чистом Python — openssl и
    установленный xray не нужны. Порт: если не задан, берём дефолт пресета
    или 443.
    """
    prepared = dict(data)
    if str(prepared.get("security") or "").lower() == "reality":
        if not str(prepared.get("private_key") or "").strip():
            private_key, public_key = xray.generate_reality_keypair()
            prepared["private_key"] = private_key
            prepared["public_key"] = public_key
        if not str(prepared.get("short_id") or "").strip():
            prepared["short_id"] = xray.generate_short_id(8)
    if not str(prepared.get("short_id") or "").strip():
        prepared["short_id"] = xray.generate_short_id(8)
    if not prepared.get("port"):
        prepared["port"] = 443
    return prepared


@get("/api/nodes/meta")
def nodes_meta(req: Request) -> Response:
    """Пресеты автонастройки, совместимость протоколов и каталог SNI."""
    return json_response(nodecfg.meta())


@get("/api/sni")
def sni_index(req: Request) -> Response:
    items = sni.catalog()
    return json_response(
        {
            "items": items,
            "total": len(items),
            "builtin": len(sni.BUILTIN),
            "custom": sni.custom(),
            "default": sni.default(),
        }
    )


@post("/api/sni")
def sni_add(req: Request) -> Response:
    try:
        result = sni.add_custom(str(req.json().get("domain") or ""))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    _audit(req, "sni.add", str(result["domain"]))
    return json_response({**result, "items": sni.catalog()}, status=201)


@delete(r"/api/sni/(?P<domain>[^/]+)")
def sni_delete(req: Request) -> Response:
    if not sni.remove_custom(req.params["domain"]):
        raise ApiError(404, "Такого SNI нет в списке")
    _audit(req, "sni.delete", req.params["domain"])
    return json_response({"ok": True, "items": sni.catalog()})


@post("/api/nodes")
def nodes_create(req: Request) -> Response:
    try:
        node_id = repo.create_node(_node_payload(req.json()))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = _node_or_404(node_id)
    _audit(req, "node.create", row["name"], f"id={node_id}")
    return json_response(repo.serialize_node(row, with_secrets=True), status=201)


@get(r"/api/nodes/(?P<node_id>\d+)")
def nodes_show(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    data = repo.serialize_node(row, with_secrets=True)
    data["config"] = xray.build_config(
        row,
        repo.node_traffic_users(row["id"]),
        db.get_settings(),
        repo.list_outbounds(with_secrets=True),
    )
    data["users_count"] = len(repo.node_traffic_users(row["id"]))
    data["base_url"] = req.base_url()
    data["config_revision"] = _config_revision(row["id"], repo.node_traffic_users(row["id"]))
    data["installed"] = bool((row["last_seen"] or "").strip())
    return json_response(data)


@patch(r"/api/nodes/(?P<node_id>\d+)")
def nodes_update(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    payload = _node_payload(req.json(), fill=False)
    merged = {key: value for key, value in dict(row).items() if key in repo.NODE_FIELDS}
    merged.update(payload)
    # Сменили транспорт/протокол — flow Vision больше не актуален, снимаем его.
    if "flow" not in payload and str(merged.get("flow") or "") and not nodecfg.supports_vision(
        str(merged.get("protocol") or ""), str(merged.get("transport") or ""), str(merged.get("security") or "")
    ):
        merged["flow"] = ""
        payload["flow"] = ""
    # Переключили ноду на Reality (или очистили ключи) — достраиваем секреты,
    # чтобы конфиг оставался валидным без ручного ввода.
    ensured = _auto_node_secrets(merged)
    for key in ("private_key", "public_key", "short_id"):
        if ensured.get(key) and ensured.get(key) != merged.get(key):
            payload[key] = ensured[key]
            merged[key] = ensured[key]
    try:
        nodecfg.validate(merged)
        repo.update_node(row["id"], payload)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    if payload.get("sni"):
        sni.remember(str(payload["sni"]))
    updated = _node_or_404(row["id"])
    _audit(req, "node.update", updated["name"], f"id={row['id']}")
    return json_response(repo.serialize_node(updated, with_secrets=True))


@delete(r"/api/nodes/(?P<node_id>\d+)")
def nodes_delete(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    repo.delete_node(row["id"])
    _audit(req, "node.delete", row["name"], f"id={row['id']}")
    return json_response({"ok": True})


@get(r"/api/nodes/(?P<node_id>\d+)/connect")
def nodes_connect(req: Request) -> Response:
    """Команда установки ноды на новом сервере."""
    row = _node_or_404(req.params["node_id"])
    install_token = repo.node_install_token(row["id"])
    payload = nodeinstall.connect_payload(
        repo.serialize_node(row, with_secrets=True),
        req.base_url(),
        install_token,
        tls_domain=(row["sni"] or "") if row["security"] == "tls" else "",
        acme_email=db.get_settings().get("acme_email", ""),
    )
    payload["node"] = {
        "id": row["id"],
        "name": row["name"],
        "port": to_int(row["port"]),
        "transport": row["transport"],
        "security": row["security"],
    }
    return json_response(payload)


@post(r"/api/nodes/(?P<node_id>\d+)/install-token")
def nodes_install_token(req: Request) -> Response:
    """Перевыпуск токена установки: старые команды перестают работать."""
    row = _node_or_404(req.params["node_id"])
    value = repo.node_install_token(row["id"], rotate=True)
    _audit(req, "node.rotate_install_token", row["name"], f"id={row['id']}")
    return json_response(
        nodeinstall.connect_payload(
            repo.serialize_node(row, with_secrets=True),
            req.base_url(),
            value,
            tls_domain=(row["sni"] or "") if row["security"] == "tls" else "",
            acme_email=db.get_settings().get("acme_email", ""),
        )
    )


@post(r"/api/nodes/(?P<node_id>\d+)/drain")
def nodes_drain(req: Request) -> Response:
    """Вывести сервер из новых подписок (или вернуть в работу)."""
    row = _node_or_404(req.params["node_id"])
    drain = to_bool(req.json().get("drain", True))
    repo.update_node(row["id"], {"drain": drain})
    _audit(req, "node.drain" if drain else "node.undrain", row["name"], str(row["id"]))
    return json_response(repo.serialize_node(_node_or_404(row["id"]), with_secrets=True))


@post(r"/api/nodes/(?P<node_id>\d+)/migrate")
def nodes_migrate(req: Request) -> Response:
    """Перевести клиентов с ноды на другую ноду."""
    row = _node_or_404(req.params["node_id"])
    payload = req.json()
    target = _node_or_404(payload.get("to_node_id", 0))
    if target["id"] == row["id"]:
        raise ApiError(400, "Выберите другой сервер")
    moved = repo.replace_user_node(row["id"], target["id"])
    _audit(req, "node.migrate", row["name"], f"→ {target['name']}: {moved}")
    return json_response({"moved": moved, "to": target["name"], "from": row["name"]})


@post(r"/api/nodes/(?P<node_id>\d+)/probe")
def nodes_probe(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    result = xray.probe(row["address"], row["port"])
    if result["ok"]:
        repo.touch_node(row["id"])
    return json_response(result)


def node_config_payload(row) -> tuple[dict[str, Any], list[str]]:
    """Собрать конфиг ноды и проверить его по схеме ядра Xray."""
    users = repo.node_traffic_users(row["id"])
    data = xray.build_config(
        row, users, db.get_settings(), repo.list_outbounds(with_secrets=True)
    )
    return data, xraycheck.validate_config(data)


@get(r"/api/nodes/(?P<node_id>\d+)/actions")
def node_actions_index(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    return json_response({"items": repo.list_node_commands(row["id"])})


@post(r"/api/nodes/(?P<node_id>\d+)/actions")
def node_actions_create(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    action = str((req.json() or {}).get("action") or "").strip()
    if action not in repo.NODE_COMMANDS:
        raise ApiError(400, "Неизвестное действие")
    actor = req.admin["username"] if req.admin else ""
    command_id = repo.create_node_command(row["id"], action, actor)
    _audit(req, f"node.action.{action}", row["name"])
    return json_response(
        {"ok": True, "id": command_id, "action": action,
         "title": repo.NODE_COMMANDS[action], "status": "pending"},
        status=201,
    )


@get(r"/api/nodes/(?P<node_id>\d+)/config")
def nodes_config(req: Request) -> Response:
    row = _node_or_404(req.params["node_id"])
    data, _problems = node_config_payload(row)
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
# Двухфакторная аутентификация и API-токены
# --------------------------------------------------------------------------


@get("/api/account/2fa")
def account_2fa_status(req: Request) -> Response:
    status = auth.totp_status(req.admin["id"])
    status["issuer"] = db.get_setting("panel_title", "DF_Xray") or "DF_Xray"
    return json_response(status)


@post("/api/account/2fa/start")
def account_2fa_start(req: Request) -> Response:
    admin = auth.get_admin(req.admin["id"])
    if admin is None:
        raise ApiError(404, "Администратор не найден")
    title = db.get_setting("panel_title", "DF_Xray") or "DF_Xray"
    data = auth.begin_totp(admin["id"], issuer=title, account=admin["username"])
    data["qr_svg"] = qr.svg(data["uri"], module_px=5, border=2, title="2FA")
    _audit(req, "account.2fa_start")
    return json_response(data)


@post("/api/account/2fa/enable")
def account_2fa_enable(req: Request) -> Response:
    code = str(req.json().get("code") or "")
    if not auth.confirm_totp(req.admin["id"], code):
        raise ApiError(400, "Код не подошёл. Проверьте время на телефоне")
    _audit(req, "account.2fa_enabled")
    return json_response(auth.totp_status(req.admin["id"]))


@post("/api/account/2fa/disable")
def account_2fa_disable(req: Request) -> Response:
    payload = req.json()
    admin = auth.find_admin(req.admin["username"])
    if admin is None or not auth.verify_password(
        payload.get("password") or "", admin["password_hash"]
    ):
        raise ApiError(403, "Неверный пароль")
    auth.disable_totp(req.admin["id"])
    _audit(req, "account.2fa_disabled")
    return json_response({"enabled": False})


@post("/api/account/2fa/recovery")
def account_2fa_recovery(req: Request) -> Response:
    if not auth.totp_status(req.admin["id"])["enabled"]:
        raise ApiError(400, "Сначала включите двухфакторную аутентификацию")
    admin = auth.find_admin(req.admin["username"])
    if admin is None or not auth.verify_password(
        req.json().get("password") or "", admin["password_hash"]
    ):
        raise ApiError(403, "Неверный пароль")
    codes = auth.regenerate_recovery(req.admin["id"])
    _audit(req, "account.2fa_recovery")
    return json_response({"recovery_codes": codes})


@get("/api/tokens")
def tokens_index(req: Request) -> Response:
    items = auth.list_api_tokens()
    return json_response({"items": items, "total": len(items)})


@post("/api/tokens")
def tokens_create(req: Request) -> Response:
    payload = req.json()
    try:
        raw, item = auth.create_api_token(
            payload.get("name") or "",
            payload.get("scope") or "read",
            to_int(payload.get("expires_days")),
            req.admin.get("username", ""),
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    _audit(req, "token.create", item["name"], f"scope={item['scope']}")
    return json_response({**item, "token": raw}, status=201)


@delete(r"/api/tokens/(?P<token_id>\d+)")
def tokens_delete(req: Request) -> Response:
    if not auth.delete_api_token(to_int(req.params["token_id"])):
        raise ApiError(404, "Токен не найден")
    _audit(req, "token.delete", req.params["token_id"])
    return json_response({"ok": True})


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
    "sub_sort_by_latency",
    "update_auto",
)
INT_SETTINGS = (
    "sub_update_interval",
    "default_days",
    "default_device_limit",
    "traffic_retention_days",
)


@get("/api/notifications")
def notifications_info(req: Request) -> Response:
    data = notify.serialize_settings()
    data["pending"] = notify.pending_state()
    return json_response(data)


@patch("/api/notifications")
def notifications_update(req: Request) -> Response:
    payload = req.json()
    fields = {
        "notify_enabled": "1" if to_bool(payload.get("enabled")) else "0",
        "notify_telegram_token": str(payload.get("telegram_token") or "").strip(),
        "notify_telegram_chat": str(payload.get("telegram_chat") or "").strip(),
        "notify_webhook": str(payload.get("webhook") or "").strip(),
    }
    events = payload.get("events")
    if events is not None:
        if not isinstance(events, list):
            raise ApiError(400, "events должен быть списком")
        unknown = [item for item in events if item not in notify.EVENTS]
        if unknown:
            raise ApiError(400, f"Неизвестные события: {', '.join(map(str, unknown))}")
        fields["notify_events"] = ",".join(str(item) for item in events)
    for key, value in fields.items():
        db.set_setting(key, value)
    _audit(req, "notify.update", "уведомления", f"enabled={fields['notify_enabled']}")
    return json_response(notify.serialize_settings())


@post("/api/notifications/test")
def notifications_test(req: Request) -> Response:
    result = notify.test()
    _audit(req, "notify.test", "уведомления", "ok" if result["ok"] else "fail")
    if not result["ok"]:
        raise ApiError(400, result.get("error") or "Не удалось отправить сообщение")
    return json_response(result)


@post("/api/notifications/check")
def notifications_check(req: Request) -> Response:
    sent = notify.check_once()
    return json_response({"sent": sent, "total": len(sent)})


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
    "route_default_outbound": str,
    "update_auto": bool,
    "update_command": str,
    "install_dir": str,
    "sub_sort_by_latency": bool,
    "acme_email": str,
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
    config_data, problems = node_config_payload(node)
    if problems:
        repo.update_node(node["id"], {"last_error": "схема конфига: " + "; ".join(problems)[:360]})
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
            "problems": problems,
            "commands": repo.node_commands_queue(node["id"]),
        }
    )


@post("/api/agent/command", auth_required=False)
def agent_command_result(req: Request) -> Response:
    node = _agent_node(req)
    payload = req.json()
    command_id = to_int(payload.get("id"))
    if not command_id:
        raise ApiError(400, "Не указан id команды")
    row = db.one("SELECT * FROM node_commands WHERE id = ? AND node_id = ?", (command_id, node["id"]))
    if row is None:
        raise ApiError(404, "Команда не найдена")
    repo.finish_node_command(command_id, str(payload.get("status") or "done"),
                             str(payload.get("result") or ""))
    return json_response({"ok": True})


@post("/api/agent/heartbeat", auth_required=False)
def agent_heartbeat(req: Request) -> Response:
    node = _agent_node(req)
    payload = req.json()
    repo.update_node_metrics(node["id"], payload)
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
    repo.update_node_metrics(node["id"], payload)
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


# --------------------------------------------------------------------------
# Установка ноды (публичные файлы по токену установки)
# --------------------------------------------------------------------------


@get(r"/api/node/install/(?P<install_token>[A-Za-z0-9_\-]+)\.sh", auth_required=False)
def node_install_script(req: Request) -> Response:
    row = repo.get_node_by_install_token(req.params["install_token"])
    if row is None:
        raise ApiError(404, "Ссылка установки устарела — перевыпустите её в панели")
    script = nodeinstall.install_script(
        url=req.base_url(),
        node_token=row["agent_token"],
        node_name=row["name"],
        port=to_int(row["port"], 443),
        agent_url=f"{req.base_url()}/api/node/agent.py",
    )
    return Response(
        script,
        content_type="text/x-shellscript; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="dfxray-node-{row["id"]}.sh"',
        },
    )


@get("/api/node/agent.py", auth_required=False)
def node_agent_source(req: Request) -> Response:
    path = config.ROOT_DIR / "node" / "agent.py"
    if not path.is_file():
        raise ApiError(404, "Файл агента не найден")
    return Response(
        path.read_bytes(),
        content_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="dfxray-agent.py"',
        },
    )


# --------------------------------------------------------------------------
# Группы клиентов
# --------------------------------------------------------------------------


@get("/api/groups")
def groups_index(req: Request) -> Response:
    items = repo.list_groups()
    return json_response({"items": items, "total": len(items)})


@post("/api/groups")
def groups_create(req: Request) -> Response:
    try:
        group_id = repo.create_group(req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    _audit(req, "group.create", str(req.json().get("name") or ""), f"id={group_id}")
    row = repo.get_group(group_id)
    return json_response(repo.serialize_group(row), status=201)


@patch(r"/api/groups/(?P<group_id>\d+)")
def groups_update(req: Request) -> Response:
    group_id = to_int(req.params["group_id"])
    try:
        repo.update_group(group_id, req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = repo.get_group(group_id)
    if row is None:
        raise ApiError(404, "Группа не найдена")
    _audit(req, "group.update", row["name"], f"id={group_id}")
    return json_response(repo.serialize_group(row))


@delete(r"/api/groups/(?P<group_id>\d+)")
def groups_delete(req: Request) -> Response:
    group_id = to_int(req.params["group_id"])
    row = repo.get_group(group_id)
    if row is None:
        raise ApiError(404, "Группа не найдена")
    repo.delete_group(group_id)
    _audit(req, "group.delete", row["name"], f"id={group_id}")
    return json_response({"ok": True})


# --------------------------------------------------------------------------
# Исходящие
# --------------------------------------------------------------------------


@get("/api/outbounds")
def outbounds_index(req: Request) -> Response:
    items = repo.list_outbounds(with_secrets=req.q("secrets") == "1")
    return json_response(
        {
            "items": items,
            "total": len(items),
            "types": list(repo.OUTBOUND_TYPES),
            "default": db.get_setting("route_default_outbound", ""),
        }
    )


@post("/api/outbounds")
def outbounds_create(req: Request) -> Response:
    try:
        outbound_id = repo.create_outbound(req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = repo.get_outbound(outbound_id)
    _audit(req, "outbound.create", row["name"] if row else "", f"id={outbound_id}")
    return json_response(repo.serialize_outbound(row, with_secrets=True), status=201)


@patch(r"/api/outbounds/(?P<outbound_id>\d+)")
def outbounds_update(req: Request) -> Response:
    outbound_id = to_int(req.params["outbound_id"])
    try:
        repo.update_outbound(outbound_id, req.json())
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    row = repo.get_outbound(outbound_id)
    if row is None:
        raise ApiError(404, "Исходящий не найден")
    _audit(req, "outbound.update", row["name"], f"id={outbound_id}")
    return json_response(repo.serialize_outbound(row, with_secrets=True))


@delete(r"/api/outbounds/(?P<outbound_id>\d+)")
def outbounds_delete(req: Request) -> Response:
    outbound_id = to_int(req.params["outbound_id"])
    row = repo.get_outbound(outbound_id)
    if row is None:
        raise ApiError(404, "Исходящий не найден")
    repo.delete_outbound(outbound_id)
    _audit(req, "outbound.delete", row["name"], f"id={outbound_id}")
    return json_response({"ok": True})


# --------------------------------------------------------------------------
# Хосты (домены масок из нод)
# --------------------------------------------------------------------------


def _split_host(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("["):  # IPv6
        return value.split("]")[0].lstrip("[")
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


@get("/api/hosts")
def hosts_index(req: Request) -> Response:
    nodes = repo.list_nodes(with_secrets=True)
    hosts: dict[str, dict[str, Any]] = {}
    for node in nodes:
        values = [node.get("sni") or "", _split_host(node.get("dest") or "")]
        for host in dict.fromkeys(v.strip() for v in values if v and v.strip()):
            entry = hosts.setdefault(
                host,
                {
                    "host": host,
                    "nodes": [],
                    "protocols": [],
                    "securities": [],
                    "ports": [],
                    "reality": False,
                },
            )
            entry["nodes"].append({"id": node["id"], "name": node["name"]})
            if node.get("protocol") not in entry["protocols"]:
                entry["protocols"].append(node.get("protocol"))
            if node.get("security") not in entry["securities"]:
                entry["securities"].append(node.get("security"))
            if node.get("port") not in entry["ports"]:
                entry["ports"].append(node.get("port"))
            if node.get("security") == "reality":
                entry["reality"] = True
    items = sorted(hosts.values(), key=lambda item: item["host"].lower())
    for item in items:
        item["nodes_count"] = len(item["nodes"])
    return json_response({"items": items, "total": len(items)})


# --------------------------------------------------------------------------
# Сканер целей REALITY
# --------------------------------------------------------------------------


@get("/api/reality/presets", auth_required=False)
def reality_presets(req: Request) -> Response:
    return json_response(
        {
            "presets": list(reality.DEFAULT_TARGETS),
            "port": reality.DEFAULT_PORT,
            "max_targets": reality.MAX_TARGETS,
        }
    )


@post("/api/reality/scan")
def reality_scan(req: Request) -> Response:
    payload = req.json()
    raw = str(payload.get("targets") or "").strip()
    port = to_int(payload.get("port", 443)) or 443
    if not 1 <= port <= 65535:
        raise ApiError(400, "Некорректный порт")
    timeout = payload.get("timeout", reality.DEFAULT_TIMEOUT)
    try:
        timeout_value = float(timeout)
    except (TypeError, ValueError):
        timeout_value = reality.DEFAULT_TIMEOUT
    timeout_value = min(max(timeout_value, 1.0), 15.0)
    workers = to_int(payload.get("workers", reality.DEFAULT_WORKERS))
    try:
        job = reality.MANAGER.start(raw, port=port, timeout=timeout_value, workers=workers)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    _audit(req, "reality.scan", str(len(job.targets)), f"job={job.id}")
    return json_response(
        {
            "job_id": job.id,
            "total": len(job.targets),
            "targets": [target.label for target in job.targets[:64]],
        },
        status=201,
    )


@get(r"/api/reality/scan/(?P<job_id>[A-Za-z0-9]+)")
def reality_scan_status(req: Request) -> Response:
    job = reality.MANAGER.get(req.params["job_id"])
    if job is None:
        raise ApiError(404, "Задание сканирования не найдено")
    snapshot = job.snapshot()
    counts = {"ok": 0, "weak": 0, "fail": 0}
    for item in snapshot["results"]:
        status = str(item.get("status") or "fail")
        counts[status] = counts.get(status, 0) + 1
    snapshot["counts"] = counts
    return json_response(snapshot)


@post(r"/api/reality/scan/(?P<job_id>[A-Za-z0-9]+)/cancel")
def reality_scan_cancel(req: Request) -> Response:
    ok = reality.MANAGER.cancel(req.params["job_id"])
    if not ok:
        raise ApiError(404, "Задание сканирования не найдено")
    return json_response({"ok": True})


@post("/api/reality/apply")
def reality_apply(req: Request) -> Response:
    payload = req.json()
    node = _node_or_404(payload.get("node_id", 0))
    try:
        host = reality.validate_target(str(payload.get("host") or ""))
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    port = to_int(payload.get("port", 443)) or 443
    if not 1 <= port <= 65535:
        raise ApiError(400, "Некорректный порт")
    repo.update_node(node["id"], {"sni": host, "dest": f"{host}:{port}"})
    updated = _node_or_404(node["id"])
    _audit(req, "node.reality_target", updated["name"], f"{host}:{port}")
    return json_response(repo.serialize_node(updated, with_secrets=True))


# --------------------------------------------------------------------------
# Обновления панели
# --------------------------------------------------------------------------


@get("/api/updates")
def updates_info(req: Request) -> Response:
    payload = updates.check(force=False)
    payload["capability"] = updates.capability()
    payload["status"] = updates.status()
    return json_response(payload)


@post("/api/updates/check")
def updates_check(req: Request) -> Response:
    payload = updates.check(force=True)
    payload["capability"] = updates.capability()
    payload["status"] = updates.status()
    _audit(req, "updates.check", str(payload.get("latest") or ""))
    return json_response(payload)


@post("/api/updates/apply")
def updates_apply(req: Request) -> Response:
    try:
        result = updates.start_update()
    except RuntimeError as exc:
        raise ApiError(400, str(exc)) from exc
    _audit(req, "updates.apply", result.get("command", ""))
    return json_response(result, status=202)


@get("/api/updates/status")
def updates_status(req: Request) -> Response:
    return json_response(updates.status())



# --------------------------------------------------------------------------
# Telegram-бот для продажи подписок
# --------------------------------------------------------------------------


def _bot_payload() -> dict[str, Any]:
    conf = tgbot.settings()
    token = conf.pop("token", "")
    return {
        "settings": {
            **conf,
            "token_set": bool(token),
            "token_hint": f"…{token[-4:]}" if len(token) > 8 else "",
        },
        "status": tgbot.status(),
        "orders": tgbot.list_orders(20),
    }


@get("/api/bot")
def bot_index(req: Request) -> Response:
    return json_response(_bot_payload())


@patch("/api/bot")
def bot_update(req: Request) -> Response:
    payload = req.json() or {}
    if "token" in payload and not str(payload.get("token") or "").strip():
        payload.pop("token")  # пустое поле = оставить прежний токен
    tgbot.save_settings(payload)
    if payload.get("token"):
        try:
            info = tgbot.bot_info(str(payload["token"]))
            db.update_settings({"bot_username": info["username"]})
        except Exception as exc:  # токен мог быть неверным
            raise ApiError(400, f"Telegram отклонил токен: {exc}") from exc
    tgbot.restart_worker()
    _audit(req, "bot.update", "telegram")
    return json_response(_bot_payload())


@post("/api/bot/test")
def bot_test(req: Request) -> Response:
    conf = tgbot.settings()
    try:
        info = tgbot.bot_info(conf["token"])
    except Exception as exc:
        raise ApiError(400, f"Не удалось подключиться к Telegram: {exc}") from exc
    db.update_settings({"bot_username": info["username"], "bot_last_error": ""})
    return json_response({"ok": True, "username": info["username"], "name": info["name"]})


@post("/api/bot/restart")
def bot_restart(req: Request) -> Response:
    tgbot.restart_worker()
    _audit(req, "bot.restart", "telegram")
    return json_response({"ok": True, "status": tgbot.status()})


@get("/api/bot/orders")
def bot_orders(req: Request) -> Response:
    return json_response({"items": tgbot.list_orders(50), "stats": tgbot.orders_stats()})


@post(r"/api/bot/orders/(?P<order_id>\d+)")
def bot_order_action(req: Request) -> Response:
    order_id = to_int(req.params["order_id"])
    action = str((req.json() or {}).get("action") or "").strip()
    if action == "approve":
        paid = tgbot.mark_paid(order_id)
        if paid is None:
            raise ApiError(404, "Заказ не найден")
        _audit(req, "bot.order.approve", str(order_id))
        return json_response({"ok": True, "order": paid, "access": paid.get("access") or {}})
    if action == "deny":
        tgbot.deny_order(order_id)
        _audit(req, "bot.order.deny", str(order_id))
        return json_response({"ok": True})
    raise ApiError(400, "Неизвестное действие")


# --------------------------------------------------------------------------
# Документация API
# --------------------------------------------------------------------------


@get("/api/docs")
def api_docs(req: Request) -> Response:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in ROUTES:
        pattern = item.regex.pattern
        if not pattern.startswith("^/api/"):
            continue
        sample = re.sub(r"\(\?P<(\w+)>[^)]+\)", r"{\1}", pattern[1:-1]).replace("\\.", ".")
        key = (item.method, sample)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "method": item.method,
                "path": sample,
                "auth": item.auth_required,
                "agent": sample.startswith("/api/agent/"),
            }
        )
    items.sort(key=lambda entry: (entry["path"], entry["method"]))
    return json_response(
        {
            "items": items,
            "total": len(items),
            "version": config.API_VERSION,
            "base": req.base_url(),
        }
    )
