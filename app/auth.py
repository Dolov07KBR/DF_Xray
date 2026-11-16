"""Пароли (PBKDF2-SHA256), сессии и защита от перебора."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
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


# --------------------------------------------------------------------------
# Двухфакторная аутентификация (TOTP)
# --------------------------------------------------------------------------


def _admin_row(admin_id: int):
    return db.one("SELECT * FROM admins WHERE id = ?", (admin_id,))


def totp_status(admin_id: int) -> dict[str, Any]:
    row = _admin_row(admin_id)
    if row is None:
        return {"enabled": False, "recovery_left": 0}
    try:
        codes = json.loads(row["totp_recovery"] or "[]")
    except (ValueError, TypeError):
        codes = []
    return {
        "enabled": bool(row["totp_enabled"]),
        "confirmed_at": row["totp_confirmed_at"] or "",
        "recovery_left": len(codes) if isinstance(codes, list) else 0,
    }


def begin_totp(admin_id: int, issuer: str = "DF_Xray", account: str = "") -> dict[str, Any]:
    """Сгенерировать секрет и резервные коды (2FA ещё не включена)."""
    from . import totp

    row = _admin_row(admin_id)
    if row is None:
        raise ValueError("Администратор не найден")
    secret = totp.new_secret()
    codes = totp.recovery_codes(8)
    hashed = [totp.hash_recovery(value) for value in codes]
    db.run(
        "UPDATE admins SET totp_secret = ?, totp_enabled = 0, totp_recovery = ?, "
        "totp_confirmed_at = NULL WHERE id = ?",
        (secret, json.dumps(hashed), admin_id),
    )
    return {
        "secret": secret,
        "secret_pretty": totp.address(secret),
        "uri": totp.provisioning_uri(secret, account or row["username"], issuer),
        "recovery_codes": codes,
    }


def confirm_totp(admin_id: int, value: str) -> bool:
    from . import totp

    row = _admin_row(admin_id)
    if row is None or not row["totp_secret"]:
        return False
    if not totp.verify(row["totp_secret"], value):
        return False
    db.run(
        "UPDATE admins SET totp_enabled = 1, totp_confirmed_at = ? WHERE id = ?",
        (iso(), admin_id),
    )
    db.run("DELETE FROM sessions WHERE admin_id = ?", (admin_id,))
    return True


def disable_totp(admin_id: int) -> None:
    db.run(
        "UPDATE admins SET totp_enabled = 0, totp_secret = NULL, totp_recovery = NULL, "
        "totp_confirmed_at = NULL WHERE id = ?",
        (admin_id,),
    )
    db.run("DELETE FROM sessions WHERE admin_id = ?", (admin_id,))


def check_second_factor(admin_id: int, value: str) -> bool:
    """Проверить код TOTP или резервный код (резервный сгорает)."""
    from . import totp

    row = _admin_row(admin_id)
    if row is None:
        return False
    value = (value or "").strip()
    if not value:
        return False
    if row["totp_secret"] and totp.verify(row["totp_secret"], value):
        return True
    try:
        codes = json.loads(row["totp_recovery"] or "[]")
    except (ValueError, TypeError):
        codes = []
    if not isinstance(codes, list):
        return False
    hashed = totp.hash_recovery(value)
    if hashed in codes:
        codes.remove(hashed)
        db.run("UPDATE admins SET totp_recovery = ? WHERE id = ?", (json.dumps(codes), admin_id))
        return True
    return False


def regenerate_recovery(admin_id: int) -> list[str]:
    from . import totp

    codes = totp.recovery_codes(8)
    db.run(
        "UPDATE admins SET totp_recovery = ? WHERE id = ?",
        (json.dumps([totp.hash_recovery(value) for value in codes]), admin_id),
    )
    return codes


# --------------------------------------------------------------------------
# Одноразовые challenge-токены между паролем и кодом 2FA
# --------------------------------------------------------------------------

CHALLENGE_TTL = 300


def create_challenge(admin_id: int) -> str:
    raw = token(24)
    import datetime as dt

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=CHALLENGE_TTL)
    db.run(
        "INSERT INTO login_challenges(token_hash, admin_id, created_at, expires_at) VALUES(?,?,?,?)",
        (_session_hash(raw), admin_id, iso(), expires.strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    return raw


def resolve_challenge(raw: str | None) -> int | None:
    if not raw:
        return None
    row = db.one(
        "SELECT admin_id, expires_at FROM login_challenges WHERE token_hash = ?",
        (_session_hash(raw),),
    )
    if row is None:
        return None
    if (row["expires_at"] or "") < iso():
        db.run("DELETE FROM login_challenges WHERE token_hash = ?", (_session_hash(raw),))
        return None
    return int(row["admin_id"])


def drop_challenge(raw: str | None) -> None:
    if raw:
        db.run("DELETE FROM login_challenges WHERE token_hash = ?", (_session_hash(raw),))


# --------------------------------------------------------------------------
# API-токены для автоматизации
# --------------------------------------------------------------------------

TOKEN_SCOPES = ("read", "write")


def create_api_token(
    name: str, scope: str = "read", expires_days: int = 0, created_by: str = ""
) -> tuple[str, dict[str, Any]]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажите название токена")
    scope = (scope or "read").strip().lower()
    if scope not in TOKEN_SCOPES:
        raise ValueError("Неизвестный уровень доступа")
    raw = "dfx_" + token(24)
    prefix = raw[:12]
    import datetime as dt

    expires = ""
    if expires_days > 0:
        expires = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=expires_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    token_id = db.run(
        "INSERT INTO api_tokens(name, prefix, token_hash, scope, created_by, created_at, expires_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (name, prefix, sha256(raw), scope, created_by[:64], iso(), expires or None),
    )
    row = db.one("SELECT * FROM api_tokens WHERE id = ?", (token_id,))
    return raw, serialize_api_token(row)


def serialize_api_token(row: Any, with_value: str = "") -> dict[str, Any]:
    data = dict(row)
    result = {
        "id": data["id"],
        "name": data["name"],
        "prefix": data["prefix"],
        "scope": data["scope"],
        "created_by": data.get("created_by") or "",
        "created_at": data.get("created_at") or "",
        "last_used_at": data.get("last_used_at") or "",
        "expires_at": data.get("expires_at") or "",
    }
    if with_value:
        result["token"] = with_value
    return result


def list_api_tokens() -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM api_tokens ORDER BY id DESC")
    return [serialize_api_token(row) for row in rows]


def delete_api_token(token_id: int) -> bool:
    row = db.one("SELECT id FROM api_tokens WHERE id = ?", (token_id,))
    if row is None:
        return False
    db.run("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    return True


def verify_api_token(raw: str) -> dict[str, Any] | None:
    value = (raw or "").strip()
    if not value:
        return None
    row = db.one("SELECT * FROM api_tokens WHERE token_hash = ?", (sha256(value),))
    if row is None:
        return None
    if row["expires_at"] and row["expires_at"] < iso():
        db.run("DELETE FROM api_tokens WHERE id = ?", (row["id"],))
        return None
    db.run("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (iso(), row["id"]))
    return {
        "id": 0,
        "username": f"token:{row['name']}",
        "token_id": row["id"],
        "scope": row["scope"],
        "created_at": row["created_at"],
    }
