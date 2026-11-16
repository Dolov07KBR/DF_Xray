"""Конфигурация DF_Xray Panel.

Всё читается из переменных окружения, чтобы панель одинаково работала
и локально (python -m app), и в Docker Compose.
"""

from __future__ import annotations

import os
import pathlib

APP_NAME = "DF_Xray Panel"
APP_VERSION = "1.5.1"
API_VERSION = 1

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent

# Каталог данных: SQLite, сгенерированные конфиги, бэкапы.
DATA_DIR = pathlib.Path(os.environ.get("DFX_DATA_DIR", ROOT_DIR / "data")).resolve()
DB_PATH = pathlib.Path(os.environ.get("DFX_DB_PATH", DATA_DIR / "panel.db")).resolve()

# HTTP
HOST = os.environ.get("DFX_HOST", "0.0.0.0")
PORT = int(os.environ.get("DFX_PORT", "8000"))
# Публичный адрес панели (для ссылок подписок). Если не задан —
# вычисляется из заголовков запроса.
BASE_URL = os.environ.get("DFX_BASE_URL", "").rstrip("/")
# Доверять X-Forwarded-* (когда панель за nginx/Caddy/Traefik).
TRUST_PROXY = os.environ.get("DFX_TRUST_PROXY", "1") not in ("0", "false", "no")

# Сессии
SESSION_COOKIE = "dfx_session"
SESSION_TTL_HOURS = int(os.environ.get("DFX_SESSION_TTL_HOURS", 24 * 7))

# Первичный администратор (создаётся только при пустой базе)
BOOTSTRAP_USERNAME = os.environ.get("DFX_ADMIN_USERNAME", "admin")
BOOTSTRAP_PASSWORD = os.environ.get("DFX_ADMIN_PASSWORD", "")
DEFAULT_PASSWORD_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

# Демо-данные при первом запуске (nodes/users) — только для витрины.
SEED_DEMO = os.environ.get("DFX_SEED_DEMO", "0") in ("1", "true", "yes", "on")

# Агент ноды
AGENT_POLL_SECONDS = int(os.environ.get("DFX_AGENT_POLL", "30"))
NODE_OFFLINE_AFTER_SECONDS = int(os.environ.get("DFX_NODE_OFFLINE_AFTER", "180"))

STATIC_DIR = ROOT_DIR / "static"


def ensure_dirs() -> None:
    for d in (DATA_DIR, DATA_DIR / "nodes"):
        d.mkdir(parents=True, exist_ok=True)
