"""Каталог SNI-доменов и пресеты автонастройки ноды.

Панель хранит три источника SNI: встроенный проверенный список, добавленные
администратором домены и недавно использованные в нодах. Список нужен форме
ноды (выбор из выпадающего списка) и окну «SNI» с проверкой доступности.
"""

from __future__ import annotations

from . import db, reality

SETTING_CUSTOM = "custom_sni"
SETTING_RECENT = "sni_recent"
MAX_CUSTOM = 200
MAX_RECENT = 20

#: Домены, которые исторически хорошо работают как маскировка Reality:
#: крупный CDN, TLS 1.3, HTTP/2, стабильные сертификаты.
BUILTIN: tuple[dict[str, str], ...] = (
    {"domain": "www.microsoft.com", "note": "Microsoft · TLS 1.3, h2"},
    {"domain": "github.com", "note": "GitHub · TLS 1.3, h2"},
    {"domain": "www.cloudflare.com", "note": "Cloudflare · TLS 1.3, h2"},
    {"domain": "www.apple.com", "note": "Apple · TLS 1.3, h2"},
    {"domain": "www.amazon.com", "note": "Amazon · TLS 1.3, h2"},
    {"domain": "www.nvidia.com", "note": "NVIDIA · TLS 1.3, h2"},
    {"domain": "www.samsung.com", "note": "Samsung · TLS 1.3, h2"},
    {"domain": "www.intel.com", "note": "Intel · TLS 1.3, h2"},
    {"domain": "aws.amazon.com", "note": "AWS Console · TLS 1.3, h2"},
    {"domain": "www.bing.com", "note": "Bing · TLS 1.3, h2"},
    {"domain": "discord.com", "note": "Discord · TLS 1.3, h2"},
    {"domain": "www.speedtest.net", "note": "Speedtest · TLS 1.3, h2"},
    {"domain": "www.wikipedia.org", "note": "Wikipedia · TLS 1.3, h2"},
)

DEFAULT_DOMAIN = BUILTIN[0]["domain"]


def _split(value: str) -> list[str]:
    return [item.strip().lower() for item in (value or "").split(",") if item.strip()]


def custom() -> list[str]:
    return _split(db.get_setting(SETTING_CUSTOM, ""))


def recent() -> list[str]:
    return _split(db.get_setting(SETTING_RECENT, ""))


def _save(key: str, values: list[str]) -> None:
    db.set_setting(key, ",".join(values))


def normalize(domain: str) -> str:
    """Проверить домен и вернуть его в нижнем регистре без схемы."""
    raw = (domain or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.split("/", 1)[0].strip().rstrip(".")
    if not raw:
        raise ValueError("Введите домен")
    host = reality.validate_target(raw)
    if host.replace(".", "").isdigit():
        raise ValueError("Для SNI нужен домен, а не IP-адрес")
    return host


def add_custom(domain: str) -> dict[str, object]:
    host = normalize(domain)
    if host in {item["domain"] for item in BUILTIN}:
        return {"domain": host, "source": "builtin", "added": False}
    existing = custom()
    if host in existing:
        return {"domain": host, "source": "custom", "added": False}
    values = [item for item in existing if item != host]
    values.insert(0, host)
    if len(values) > MAX_CUSTOM:
        values = values[:MAX_CUSTOM]
    _save(SETTING_CUSTOM, values)
    return {"domain": host, "source": "custom", "added": True}


def remove_custom(domain: str) -> bool:
    host = (domain or "").strip().lower()
    values = custom()
    if host not in values:
        return False
    _save(SETTING_CUSTOM, [item for item in values if item != host])
    return True


def remember(domain: str) -> None:
    """Запомнить домен, который уже используется в нодах."""
    host = (domain or "").strip().lower()
    if not host or "." not in host:
        return
    values = [item for item in recent() if item != host]
    values.insert(0, host)
    _save(SETTING_RECENT, values[:MAX_RECENT])


def catalog() -> list[dict[str, object]]:
    """Все известные SNI: встроенные, свои и недавние — без дублей."""
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in BUILTIN:
        host = entry["domain"]
        seen.add(host)
        items.append({"domain": host, "note": entry["note"], "source": "builtin"})
    for host in custom():
        if host in seen:
            continue
        seen.add(host)
        items.append({"domain": host, "note": "добавлен вручную", "source": "custom"})
    for host in recent():
        if host in seen:
            continue
        seen.add(host)
        items.append({"domain": host, "note": "используется в нодах", "source": "recent"})
    return items


def default(exclude: tuple[str, ...] = ()) -> str:
    """Первый домен каталога, которого ещё нет в нодах."""
    used = {item.lower() for item in exclude}
    for item in catalog():
        if item["domain"] not in used:
            return str(item["domain"])
    return DEFAULT_DOMAIN


def suggest(address: str = "") -> str:
    """Домен, который не совпадает с адресом самой ноды."""
    host = (address or "").strip().lower()
    if host:
        return default(exclude=(host,))
    return DEFAULT_DOMAIN
