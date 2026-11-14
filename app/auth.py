"""Пароли (PBKDF2-SHA256), сессии и защита от перебора."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from typing import Any

from . import config, db
from .utils import iso, now, sha256, token

_ITERATIONS = 210_000
_ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "$".join(
        (
            _ALGO,
            str(_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_admin(username: str, password: str) -> int:
    username = (username or "").strip()
    if not username:
        raise ValueError("Имя пользователя обязательно")
    if len(password or "") < 4:
        raise ValueError("Пароль должен быть не короче 4 символов")
    return db.run(
        "INSERT INTO admins(username, password_hash, created_at) VALUES(?,?,?)",
        (username, hash_password(password), iso()),
    )


def get_admin(admin_id: int) -> dict[str, Any] | None:
    row = db.one(
        "SELECT id, username, created_at, last_login_at, last_login_ip "
        "FROM admins WHERE id = ?",
        (admin_id,),
    )
    return dict(row) if row else None


def find_admin(username: str):
    return db.one("SELECT * FROM admins WHERE username = ?", ((username or "").strip(),))


def set_password(admin_id: int, new_password: str) -> None:
    if len(new_password or "") < 4:
        raise ValueError("Пароль должен быть не короче 4 символов")
    db.run(
        "UPDATE admins SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), admin_id),
    )
    db.set_setting("password_changed", "1")
    # Все прочие сессии администратора закрываем.
    db.run("DELETE FROM sessions WHERE admin_id = ?", (admin_id,))


def _session_hash(raw: str) -> str:
    return sha256(raw)


def create_session(admin_id: int, ip: str = "", user_agent: str = "") -> str:
    raw = token(32)
    expires = now().timestamp() + config.SESSION_TTL_HOURS * 3600
    import datetime as dt

    expires_iso = dt.datetime.fromtimestamp(expires, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    db.run(
        "INSERT INTO sessions(token_hash, admin_id, created_at, expires_at, ip, user_agent) "
        "VALUES(?,?,?,?,?,?)",
        (_session_hash(raw), admin_id, iso(), expires_iso, ip, (user_agent or "")[:255]),
    )
    db.run(
        "UPDATE admins SET last_login_at = ?, last_login_ip = ? WHERE id = ?",
        (iso(), ip, admin_id),
    )
    return raw


def resolve_session(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    row = db.one(
        "SELECT a.id, a.username, a.created_at, a.last_login_at, s.expires_at "
        "FROM sessions s JOIN admins a ON a.id = s.admin_id "
        "WHERE s.token_hash = ?",
        (_session_hash(raw),),
    )
    if row is None:
        return None
    if (row["expires_at"] or "") < iso():
        db.run("DELETE FROM sessions WHERE token_hash = ?", (_session_hash(raw),))
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def delete_session(raw: str | None) -> None:
    if raw:
        db.run("DELETE FROM sessions WHERE token_hash = ?", (_session_hash(raw),))


def delete_other_sessions(admin_id: int, keep_raw: str | None) -> int:
    keep = _session_hash(keep_raw) if keep_raw else ""
    with db.tx() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE admin_id = ? AND token_hash != ?",
            (admin_id, keep),
        )
        return cur.rowcount or 0


def cleanup_sessions() -> None:
    db.run("DELETE FROM sessions WHERE expires_at < ?", (iso(),))


# --- защита от перебора ----------------------------------------------------

_ATTEMPTS: dict[str, list[float]] = {}
_LOCK = threading.Lock()
_WINDOW = 300.0
_LIMIT = 8


def login_allowed(ip: str) -> bool:
    with _LOCK:
        stamps = [t for t in _ATTEMPTS.get(ip, []) if time.time() - t < _WINDOW]
        _ATTEMPTS[ip] = stamps
        return len(stamps) < _LIMIT


def record_failed_login(ip: str) -> None:
    with _LOCK:
        _ATTEMPTS.setdefault(ip, []).append(time.time())


def clear_login_attempts(ip: str) -> None:
    with _LOCK:
        _ATTEMPTS.pop(ip, None)
