"""QR-коды без внешних зависимостей: SVG и PNG из матрицы вендорного энкодера."""

from __future__ import annotations

import struct
import zlib
from xml.sax.saxutils import escape

from .vendor.qrcode import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, QRCode

_ECC = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q}

DARK = "#0d1220"
LIGHT = "#ffffff"


def _matrix(data: str, ecc: str = "M", border: int = 2) -> list[list[bool]]:
    qr = QRCode(
        error_correction=_ECC.get(ecc.upper(), ERROR_CORRECT_M),
        box_size=1,
        border=0,
    )
    qr.add_data(data)
    qr.make(fit=True)
    modules = qr.get_matrix()
    if border <= 0:
        return [list(row) for row in modules]
    width = len(modules) + border * 2
    result = [[False] * width for _ in range(border)]
    for row in modules:
        result.append([False] * border + [bool(c) for c in row] + [False] * border)
    result.extend([[False] * width for _ in range(border)])
    return result


def svg(
    data: str,
    *,
    module_px: int = 8,
    border: int = 2,
    ecc: str = "M",
    dark: str = DARK,
    light: str = LIGHT,
    title: str = "QR-код",
) -> str:
    matrix = _matrix(data, ecc, border)
    size = len(matrix)
    # Рисуем «умные» прямоугольники: горизонтальные полосы модулей подряд.
    parts: list[str] = []
    for y, row in enumerate(matrix):
        x = 0
        while x < size:
            if not row[x]:
                x += 1
                continue
            start = x
            while x < size and row[x]:
                x += 1
            parts.append(f"M{start} {y}h{x - start}v1h-{x - start}z")
    path = "".join(parts)
    px = size * module_px
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" '
        f'viewBox="0 0 {size} {size}" role="img" aria-label="{escape(title)}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="{light}"/>'
        f'<path d="{path}" fill="{dark}"/>'
        f"</svg>"
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png(
    data: str,
    *,
    scale: int = 8,
    border: int = 2,
    ecc: str = "M",
    dark=(13, 18, 32),
    light=(255, 255, 255),
) -> bytes:
    matrix = _matrix(data, ecc, border)
    modules = len(matrix)
    width = modules * scale
    raw = bytearray()
    for y in range(modules):
        row = bytearray()
        for x in range(modules):
            pixel = bytes(dark if matrix[y][x] else light)
            row.extend(pixel * scale)
        for _ in range(scale):
            raw.append(0)  # filter type: none
            raw.extend(row)
    header = struct.pack(">IIBBBBB", width, width, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def data_uri(data: str, **kwargs) -> str:
    """Инлайн SVG для вставки в HTML без отдельного запроса."""
    import base64

    encoded = base64.b64encode(svg(data, **kwargs).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


__all__ = ["data_uri", "png", "svg"]
