"""X25519 (Curve25519) на чистом Python — чтобы ключи Reality генерировались
без openssl и без бинаря xray.

Реализация повторяет RFC 7748: скалярное умножение Монтгомери, зажим скаляра,
кодирование little-endian. Формат результата совпадает с `xray x25519`:
32 байта в base64url без выравнивания (43 символа).
"""

from __future__ import annotations

import base64
import os

P = 2 ** 255 - 19
A24 = 121665


def _clamp(scalar: bytes) -> int:
    """Зажать 32-байтный скаляр как требует RFC 7748."""
    if len(scalar) != 32:
        raise ValueError("скаляр X25519 должен быть длиной 32 байта")
    value = int.from_bytes(scalar, "little")
    value &= (1 << 254) - 8
    value |= 1 << 254
    return value


def x25519(scalar: bytes, u: bytes) -> bytes:
    """Скалярное умножение X25519: вернуть 32 байта общей точки."""
    k = _clamp(scalar)
    x1 = int.from_bytes(u, "little") % P
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for bit in range(254, -1, -1):
        current = (k >> bit) & 1
        swap ^= current
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = current
        a = (x2 + z2) % P
        aa = (a * a) % P
        b = (x2 - z2) % P
        bb = (b * b) % P
        e = (aa - bb) % P
        c = (x3 + z3) % P
        d = (x3 - z3) % P
        da = (d * a) % P
        cb = (c * b) % P
        x3 = ((da + cb) ** 2) % P
        z3 = (x1 * ((da - cb) ** 2)) % P
        x2 = (aa * bb) % P
        z2 = (e * ((aa + A24 * e) % P)) % P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    result = (x2 * pow(z2, P - 2, P)) % P
    return result.to_bytes(32, "little")


def public_key(private_scalar: bytes) -> bytes:
    """Публичный ключ = X25519(private, 9)."""
    return x25519(private_scalar, (9).to_bytes(32, "little"))


def b64url(raw: bytes) -> str:
    """base64url без выравнивания — так Xray печатает ключи."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    padded = text.strip() + "=" * (-len(text.strip()) % 4)
    return base64.urlsafe_b64decode(padded)


def generate() -> tuple[str, str]:
    """Новая пара ключей в формате Xray: (private, public)."""
    scalar = os.urandom(32)
    return b64url(scalar), b64url(public_key(scalar))


def derive(public_b64: str) -> str:
    """Проверить, что из публичного ключа получается валидная точка."""
    raw = b64url_decode(public_b64)
    if len(raw) != 32:
        raise ValueError("публичный ключ должен быть 32 байта")
    shared = x25519(os.urandom(32), raw)
    return b64url(shared)
