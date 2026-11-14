"""QR Code generator (vendored subset of the `qrcode` project, version 7.4.2).

Upstream: https://github.com/lincolnloop/python-qrcode
License: BSD-3-Clause (see LICENSE in this directory).
Only the pure-python QR encoder is kept; rendering is done by app/qr.py.
"""

from .constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)
from .main import QRCode

__all__ = ["ERROR_CORRECT_H", "ERROR_CORRECT_L", "ERROR_CORRECT_M", "ERROR_CORRECT_Q", "QRCode"]
