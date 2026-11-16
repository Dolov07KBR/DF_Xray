"""TOTP (RFC 6238) и резервные коды — без внешних зависимостей."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

STEP = 30
DIGITS = 6
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def new_secret(length: int = 32) -> str:
    """Случайный base32-секрет без padding (совместим с Google Authenticator)."""
    raw = secrets.token_bytes(length)
    encoded = base64.b32encode(raw).decode("ascii")
    return encoded.rstrip("=")


def _decode_secret(secret: str) -> bytes:
    value = (secret or "").strip().upper().replace(" ", "")
    padding = "=" * ((8 - len(value) % 8) % 8)
    return base64.b32decode(value + padding, casefold=True)


def code(secret: str, at: float | None = None, step: int = STEP, digits: int = DIGITS) -> str:
    """Код TOTP для указанного момента (по умолчанию — сейчас)."""
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def verify(secret: str, value: str, window: int = 1, at: float | None = None) -> bool:
    """Проверить код с допуском ±window шагов (перекос часов)."""
    value = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(value) != DIGITS or not secret:
        return False
    moment = at if at is not None else time.time()
    for shift in range(-abs(window), abs(window) + 1):
        if hmac.compare_digest(code(secret, moment + shift * STEP), value):
            return True
    return False


def provisioning_uri(secret: str, account: str, issuer: str = "DF_Xray") -> str:
    label = urllib.parse.quote(f"{issuer}:{account}", safe="")
    query = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def address(secret: str, account: str = "") -> str:
    """Секрет, сгруппированный для ручного ввода: XXXX XXXX XXXX …"""
    chunks = [secret[i:i + 4] for i in range(0, len(secret), 4)]
    return " ".join(chunks)


def recovery_codes(count: int = 8) -> list[str]:
    values = set()
    while len(values) < count:
        values.add(f"{secrets.token_hex(2)}-{secrets.token_hex(2)}")
    return sorted(values)


def hash_recovery(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
