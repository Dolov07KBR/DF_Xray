"""Мелкие утилиты: время, идентификаторы, кодирование, разбор значений."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import secrets
import urllib.parse
import uuid as uuidlib

UTC = dt.timezone.utc


def now() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def iso(value: dt.datetime | None = None) -> str:
    """Отметка времени в формате, который удобно сортировать в SQLite."""
    value = value or now()
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def today_str(offset_days: int = 0) -> str:
    return (now() + dt.timedelta(days=offset_days)).strftime("%Y-%m-%d")


def date_str(value: dt.date | dt.datetime) -> str:
    return value.strftime("%Y-%m-%d")


def days_between(date_from: str, date_to: str | None = None) -> int:
    try:
        a = dt.date.fromisoformat(date_from)
        b = dt.date.fromisoformat(date_to) if date_to else now().date()
    except ValueError:
        return 0
    return (a - b).days


def token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def new_uuid() -> str:
    return str(uuidlib.uuid4())


def new_short_id(length: int = 8) -> str:
    return secrets.token_hex(max(2, length // 2))[:length]


def _strip_pad(text: str) -> str:
    return text.rstrip("=")


def b64encode(text: str) -> str:
    return _strip_pad(base64.b64encode(text.encode("utf-8")).decode("ascii"))


def b64decode(text: str) -> str:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "replace")


def b64url(raw: bytes) -> str:
    return _strip_pad(base64.urlsafe_b64encode(raw).decode("ascii"))


def qs(params: dict[str, str | None]) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return urllib.parse.urlencode(clean, quote_via=urllib.parse.quote, safe="/:")


def url_quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def to_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default


def to_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y", "да")


def gb_to_bytes(value) -> int:
    """Гигабайты (можно дробные, 0 = без лимита) → байты."""
    if value in (None, "", 0, "0", "0.0"):
        return 0
    try:
        return int(float(value) * 1024 ** 3)
    except (TypeError, ValueError):
        return 0


def human_size(num: float | None) -> str:
    num = float(num or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(num) < 1024 or unit == "ТБ":
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} ТБ"


def slugify(value: str, fallback: str = "user") -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or fallback


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def mask_secret(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "•" * len(value)
    return f"{value[:keep]}{'•' * 8}{value[-keep:]}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
