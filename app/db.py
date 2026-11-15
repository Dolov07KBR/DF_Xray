"""SQLite-слой: подключение, схема, миграции, настройки по умолчанию."""

from __future__ import annotations

import contextlib
import sqlite3
import sys
from collections.abc import Iterable
from typing import Any

from . import config

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_login_at TEXT,
    last_login_ip TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id   INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip         TEXT,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    address       TEXT NOT NULL,
    region        TEXT,
    port          INTEGER NOT NULL DEFAULT 443,
    protocol      TEXT NOT NULL DEFAULT 'vless',
    transport     TEXT NOT NULL DEFAULT 'tcp',
    security      TEXT NOT NULL DEFAULT 'reality',
    sni           TEXT,
    fingerprint   TEXT DEFAULT 'chrome',
    private_key   TEXT,
    public_key    TEXT,
    short_id      TEXT,
    dest          TEXT,
    path          TEXT,
    service_name  TEXT,
    flow          TEXT DEFAULT 'xtls-rprx-vision',
    alpn          TEXT,
    cert_file     TEXT,
    key_file      TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'unknown',
    last_seen     TEXT,
    xray_version  TEXT,
    up_bytes      INTEGER NOT NULL DEFAULT 0,
    down_bytes    INTEGER NOT NULL DEFAULT 0,
    note          TEXT,
    sort          INTEGER NOT NULL DEFAULT 0,
    agent_token   TEXT NOT NULL,
    install_token TEXT,
    agent_version TEXT,
    xray_running  INTEGER,
    uptime_seconds INTEGER NOT NULL DEFAULT 0,
    load1         REAL NOT NULL DEFAULT 0,
    mem_used      INTEGER NOT NULL DEFAULT 0,
    mem_total     INTEGER NOT NULL DEFAULT 0,
    cfg_revision  TEXT,
    applied_at    TEXT,
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    color      TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE,
    email          TEXT,
    uuid           TEXT NOT NULL UNIQUE,
    sub_token      TEXT NOT NULL UNIQUE,
    flow           TEXT,
    limit_bytes    INTEGER NOT NULL DEFAULT 0,
    expires_at     TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1,
    note           TEXT,
    up_bytes       INTEGER NOT NULL DEFAULT 0,
    down_bytes     INTEGER NOT NULL DEFAULT 0,
    device_limit   INTEGER NOT NULL DEFAULT 0,
    node_ids       TEXT,
    group_id       INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    last_online_at TEXT,
    last_sub_at    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traffic (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL DEFAULT 0,
    day     TEXT NOT NULL,
    up      INTEGER NOT NULL DEFAULT 0,
    down    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, node_id, day)
);

CREATE TABLE IF NOT EXISTS outbounds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    tag        TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'direct',
    address    TEXT NOT NULL DEFAULT '',
    port       INTEGER NOT NULL DEFAULT 0,
    username   TEXT NOT NULL DEFAULT '',
    password   TEXT NOT NULL DEFAULT '',
    sni        TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    sort       INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor      TEXT,
    action     TEXT NOT NULL,
    target     TEXT,
    detail     TEXT,
    ip         TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_enabled ON users(enabled);
CREATE INDEX IF NOT EXISTS idx_users_expires ON users(expires_at);
CREATE INDEX IF NOT EXISTS idx_traffic_day ON traffic(day);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_admin ON sessions(admin_id);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "panel_title": "DF_Xray",
    "panel_subtitle": "Panel",
    "public_base_url": "",
    "sub_title": "DF_Xray",
    "sub_support_url": "",
    "sub_update_interval": "12",
    "sub_page_enabled": "1",
    "sub_show_nodes": "1",
    "block_bittorrent": "1",
    "block_ads": "0",
    "block_private": "1",
    "route_ru_direct": "0",
    "dns_preset": "cloudflare",
    "default_days": "30",
    "default_limit_gb": "0",
    "default_device_limit": "0",
    "traffic_retention_days": "90",
    "password_changed": "0",
    "footer_note": "",
    # маршрутизация / исходящие
    "route_default_outbound": "",
    # обновления
    "update_auto": "1",
    "update_check_ts": "",
    "update_latest": "",
    "update_url": "",
    "update_notes": "",
    "update_command": "",
    "install_dir": "/opt/dfxray",
}


def _connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextlib.contextmanager
def get():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def tx():
    """Транзакция: сначала BEGIN IMMEDIATE, чтобы не ловить «database is locked»."""
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        with contextlib.suppress(Exception):
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with get() as conn:
        return list(conn.execute(sql, tuple(params)).fetchall())


def one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with get() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def scalar(sql: str, params: Iterable[Any] = (), default: Any = 0) -> Any:
    row = one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def run(sql: str, params: Iterable[Any] = ()) -> int:
    """Выполнить запрос, вернуть lastrowid."""
    with get() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


# --- настройки -------------------------------------------------------------


def get_setting(key: str, default: str = "") -> str:
    row = one("SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["value"]


def get_settings() -> dict[str, str]:
    values = dict(DEFAULT_SETTINGS)
    for row in all("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    return values


def set_setting(key: str, value: str) -> None:
    run(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def update_settings(values: dict[str, Any]) -> None:
    with tx() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, "" if value is None else str(value)),
            )


def _migrate(conn: sqlite3.Connection) -> None:
    """Догоняющие миграции для баз, созданных старой версией."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "group_id" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN group_id INTEGER "
            "REFERENCES groups(id) ON DELETE SET NULL"
        )

    # v3: метрики агента и токен установки для мультисерверной панели.
    node_columns = {row["name"] for row in conn.execute("PRAGMA table_info(nodes)")}
    additions = {
        "region": "TEXT",
        "install_token": "TEXT",
        "agent_version": "TEXT",
        "xray_running": "INTEGER",
        "uptime_seconds": "INTEGER NOT NULL DEFAULT 0",
        "load1": "REAL NOT NULL DEFAULT 0",
        "mem_used": "INTEGER NOT NULL DEFAULT 0",
        "mem_total": "INTEGER NOT NULL DEFAULT 0",
        "cfg_revision": "TEXT",
        "applied_at": "TEXT",
        "last_error": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in node_columns:
            conn.execute(f"ALTER TABLE nodes ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_install_token ON nodes(install_token)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_traffic_node ON traffic(node_id, day)")
    if "install_token" not in node_columns:
        import secrets

        for row in conn.execute("SELECT id FROM nodes WHERE install_token IS NULL").fetchall():
            conn.execute(
                "UPDATE nodes SET install_token = ? WHERE id = ?",
                (secrets.token_urlsafe(16), row["id"]),
            )


def init() -> None:
    """Создать схему, настройки по умолчанию и первого администратора."""
    from . import auth

    config.ensure_dirs()
    with get() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    for key, value in DEFAULT_SETTINGS.items():
        if one("SELECT 1 FROM settings WHERE key = ?", (key,)) is None:
            set_setting(key, value)

    if scalar("SELECT COUNT(*) FROM admins") == 0:
        username = (config.BOOTSTRAP_USERNAME or "admin").strip()
        password = config.BOOTSTRAP_PASSWORD or config.DEFAULT_PASSWORD
        auth.create_admin(username, password)
        if not config.BOOTSTRAP_PASSWORD:
            print(
                "[dfxray] ВНИМАНИЕ: создан администратор по умолчанию "
                f"{username}/{password}. Смените пароль в настройках "
                "или задайте DFX_ADMIN_PASSWORD.",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"[dfxray] Создан администратор {username!r}.", file=sys.stderr, flush=True)
