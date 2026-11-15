"""Демо-данные для витрины: ноды, пользователи, история трафика."""

from __future__ import annotations

import datetime as dt
import random

from . import config, db, repo, xray
from .utils import b64url, iso, new_short_id, now, to_int, today_str

DEMO_USERS = [
    ("alex", "alex@example.com", 0, 90, 3, "active"),
    ("maria", "maria@example.com", 120, 30, 2, "active"),
    ("dmitry", "dmitry@example.com", 500, 14, 1, "active"),
    ("olga", "olga@example.com", 0, 7, 0, "active"),
    ("ivan", "ivan@example.com", 50, 3, 2, "active"),
    ("sergey", "sergey@example.com", 200, -5, 1, "expired"),
    ("kate", "kate@example.com", 10, 60, 1, "limited"),
    ("test", "test@example.com", 0, 45, 1, "disabled"),
]


def _fake_keys() -> tuple[str, str]:
    try:
        return xray.generate_reality_keypair()
    except RuntimeError:
        import secrets

        return b64url(secrets.token_bytes(32)), b64url(secrets.token_bytes(32))


def _has_demo() -> bool:
    return db.scalar("SELECT COUNT(*) FROM nodes") > 0 or db.scalar(
        "SELECT COUNT(*) FROM users"
    ) > 0


def run(demo: bool = True, force: bool = False) -> None:
    if not demo:
        print("[seed] схема готова, демо-данные не добавлялись")
        return
    if _has_demo() and not force:
        print("[seed] данные уже есть, пропускаю (используйте --force)")
        return

    random.seed(7)

    def _config_revision(node_id: int) -> str:
        return f"demo{node_id}"
    private_key, public_key = _fake_keys()

    nodes = [
        {
            "name": "DF · Frankfurt",
            "address": "de1.df-xray.net",
            "region": "Германия",
            "port": 443,
            "protocol": "vless",
            "transport": "tcp",
            "security": "reality",
            "sni": "www.microsoft.com",
            "dest": "www.microsoft.com:443",
            "fingerprint": "chrome",
            "private_key": private_key,
            "public_key": public_key,
            "short_id": new_short_id(8),
            "flow": "xtls-rprx-vision",
            "note": "Основная нода, Reality + Vision",
            "sort": 1,
        },
        {
            "name": "DF · Amsterdam CDN",
            "address": "nl1.df-xray.net",
            "region": "Нидерланды",
            "port": 443,
            "protocol": "vless",
            "transport": "ws",
            "security": "tls",
            "sni": "cdn.df-xray.net",
            "path": "/dfws",
            "alpn": "h2,http/1.1",
            "flow": "",
            "short_id": new_short_id(6),
            "note": "WebSocket за Cloudflare",
            "sort": 2,
        },
        {
            "name": "DF · Moscow",
            "address": "ru1.df-xray.net",
            "region": "Россия",
            "port": 8443,
            "protocol": "vmess",
            "transport": "ws",
            "security": "tls",
            "sni": "ru1.df-xray.net",
            "path": "/vm",
            "alpn": "http/1.1",
            "flow": "",
            "note": "Резервная нода (VMess)",
            "sort": 3,
        },
    ]

    node_ids: list[int] = []
    for item in nodes:
        node_id = repo.create_node(item)
        node_ids.append(node_id)
        repo.touch_node(node_id, "Xray 25.9.11")
        repo.update_node_metrics(
            node_id,
            {
                "xray_version": "Xray 25.9.11",
                "agent_version": config.APP_VERSION,
                "xray_running": True,
                "uptime": 86400 * (3 + node_id) + 3600 * node_id,
                "load1": round(0.12 * node_id, 2),
                "memory": {"used": 180 * 1024 * 1024 * node_id, "total": 2 * 1024 * 1024 * 1024},
                "revision": f"demo{node_id}",
                "last_error": "",
            },
        )
        db.run(
            "UPDATE nodes SET last_seen = ?, cfg_revision = ? WHERE id = ?",
            (
                iso(now() - dt.timedelta(seconds=25 + 20 * node_id)),
                _config_revision(node_id),
                node_id,
            ),
        )

    groups = ["Семья", "Работа", "Тесты"]
    colors = ["#7c5cff", "#3fb950", "#4f8cff"]
    group_ids: list[int] = []
    for index, group_name in enumerate(groups):
        try:
            group_ids.append(
                repo.create_group({"name": group_name, "color": colors[index % len(colors)]})
            )
        except ValueError:
            row = db.one("SELECT id FROM groups WHERE name = ?", (group_name,))
            if row:
                group_ids.append(int(row["id"]))

    outbounds = [
        {
            "name": "Германия SOCKS",
            "tag": "de-socks",
            "type": "socks",
            "address": "10.8.0.2",
            "port": 1080,
            "username": "dfx",
            "password": "demo-pass",
            "sort": 20,
        },
        {
            "name": "Резервный HTTP",
            "tag": "backup-http",
            "type": "http",
            "address": "10.8.0.3",
            "port": 3128,
            "sort": 40,
        },
    ]
    if db.scalar("SELECT COUNT(*) FROM outbounds") == 0:
        for outbound in outbounds:
            repo.create_outbound(outbound)

    for idx, (username, email, limit_gb, days, devices, state) in enumerate(DEMO_USERS):
        user_id = repo.create_user(
            {
                "username": username,
                "email": email,
                "limit_gb": limit_gb,
                "days": days,
                "device_limit": devices,
                "note": "демо-пользователь",
                "flow": "xtls-rprx-vision" if idx % 2 == 0 else "",
                "group_id": group_ids[idx % len(group_ids)] if group_ids else 0,
            }
        )
        enabled = state not in ("disabled",)
        if state == "expired":
            db.run("UPDATE users SET expires_at = ? WHERE id = ?", (today_str(-5), user_id))
        db.run(
            "UPDATE users SET enabled = ?, last_sub_at = ?, last_online_at = ? WHERE id = ?",
            (
                1 if enabled else 0,
                iso(now() - dt.timedelta(hours=random.randint(1, 40))),
                iso(now() - dt.timedelta(minutes=random.randint(3, 900))),
                user_id,
            ),
        )

    # История трафика за 21 день.
    user_rows = db.all("SELECT id FROM users")
    with db.tx() as conn:
        for offset in range(20, -1, -1):
            day = today_str(-offset)
            for row in user_rows:
                if random.random() < 0.25:
                    continue
                base = random.randint(250, 4200) * 1024 * 1024
                up = int(base * random.uniform(0.08, 0.3))
                down = base - up
                node_id = random.choice(node_ids)
                conn.execute(
                    "INSERT INTO traffic(user_id, node_id, day, up, down) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(user_id, node_id, day) DO UPDATE SET "
                    "up = up + excluded.up, down = down + excluded.down",
                    (row["id"], node_id, day, up, down),
                )
                conn.execute(
                    "UPDATE users SET up_bytes = up_bytes + ?, down_bytes = down_bytes + ? "
                    "WHERE id = ?",
                    (up, down, row["id"]),
                )

    # Суммарный трафик по нодам — для карточек и дашборда.
    for node_id in node_ids:
        row = db.one(
            "SELECT COALESCE(SUM(up),0) AS up, COALESCE(SUM(down),0) AS down "
            "FROM traffic WHERE node_id = ?",
            (node_id,),
        )
        if row:
            db.run(
                "UPDATE nodes SET up_bytes = ?, down_bytes = ? WHERE id = ?",
                (int(row["up"]), int(row["down"]), node_id),
            )

    # Ограничения: одному пользователю «дорежем» лимит, чтобы статус стал limited.
    limited = db.one("SELECT * FROM users WHERE username = 'kate'")
    if limited:
        used = to_int(limited["down_bytes"]) + to_int(limited["up_bytes"])
        db.run(
            "UPDATE users SET limit_bytes = ? WHERE id = ?",
            (max(int(used * 0.98), 1), limited["id"]),
        )

    repo.audit("seed.demo", "demo", "созданы демо-ноды и пользователи", actor="system")
    print(
        f"[seed] готово: нод {len(nodes)}, пользователей {len(DEMO_USERS)}, "
        "история трафика за 21 день"
    )
