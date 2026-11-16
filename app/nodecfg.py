"""Автонастройка ноды: пресеты протоколов и проверка совместимости.

Пресет — это набор согласованных полей ноды (протокол, транспорт, безопасность,
порт, path/service name, flow). Панель применяет пресет к форме, подставляет
подходящий SNI и сама генерирует производные значения (dest, alpn, ключи).
"""

from __future__ import annotations

from typing import Any

from . import sni

PROTOCOLS: dict[str, str] = {"vless": "VLESS", "vmess": "VMess", "trojan": "Trojan"}
TRANSPORTS: dict[str, str] = {
    "tcp": "TCP",
    "ws": "WebSocket",
    "grpc": "gRPC",
    "xhttp": "XHTTP",
    "h2": "HTTP/2",
}
SECURITIES: dict[str, str] = {"reality": "Reality", "tls": "TLS", "none": "Без шифрования"}

#: Reality работает только поверх этих транспортов.
REALITY_TRANSPORTS = ("tcp", "grpc", "xhttp")
#: Транспорты, которым нужен HTTP-путь.
PATH_TRANSPORTS = ("ws", "xhttp", "h2")
#: xtls-rprx-vision осмыслен только для VLESS + TCP + TLS/Reality.
VISION_FLOW = "xtls-rprx-vision"

PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "reality-vision",
        "title": "Reality · Vision",
        "badge": "рекомендуется",
        "hint": "VLESS + TCP + Reality + xtls-rprx-vision. Максимальная скорость, "
                "маскировка под чужой TLS-домен, сертификат не нужен.",
        "protocol": "vless",
        "transport": "tcp",
        "security": "reality",
        "flow": VISION_FLOW,
        "port": 443,
        "sni": "www.microsoft.com",
    },
    {
        "id": "reality-xhttp",
        "title": "Reality · XHTTP",
        "badge": "",
        "hint": "VLESS + XHTTP + Reality. Похож на обычный HTTPS-трафик, "
                "удобен там, где TCP-подключения режут по таймауту.",
        "protocol": "vless",
        "transport": "xhttp",
        "security": "reality",
        "flow": "",
        "port": 443,
        "path": "/dfx",
        "sni": "www.cloudflare.com",
    },
    {
        "id": "reality-grpc",
        "title": "Reality · gRPC",
        "badge": "",
        "hint": "VLESS + gRPC + Reality. Хорошо проходит через фильтры, "
                "требует поддержки gRPC в клиенте.",
        "protocol": "vless",
        "transport": "grpc",
        "security": "reality",
        "flow": "",
        "port": 443,
        "service_name": "dfxray",
        "sni": "www.nvidia.com",
    },
    {
        "id": "tls-ws",
        "title": "TLS · WebSocket",
        "badge": "",
        "hint": "VLESS + WebSocket + TLS. Нужен домен ноды и сертификат — "
                "панель выпустит его сама через certbot при установке.",
        "protocol": "vless",
        "transport": "ws",
        "security": "tls",
        "flow": "",
        "port": 8443,
        "path": "/dfws",
        "alpn": "h2,http/1.1",
    },
    {
        "id": "tls-grpc",
        "title": "TLS · gRPC",
        "badge": "",
        "hint": "VLESS + gRPC + TLS. Компактный конфиг, хорошо кешируется CDN.",
        "protocol": "vless",
        "transport": "grpc",
        "security": "tls",
        "flow": "",
        "port": 8443,
        "service_name": "dfxray",
        "alpn": "h2",
    },
    {
        "id": "vmess-ws-tls",
        "title": "VMess · TLS + WS",
        "badge": "",
        "hint": "VMess + WebSocket + TLS. Совместимость со старыми клиентами.",
        "protocol": "vmess",
        "transport": "ws",
        "security": "tls",
        "flow": "",
        "port": 8443,
        "path": "/vmess",
        "alpn": "h2,http/1.1",
    },
    {
        "id": "trojan-tls",
        "title": "Trojan · TLS",
        "badge": "",
        "hint": "Trojan + TCP + TLS. Пароль — UUID клиента, сертификат обязателен.",
        "protocol": "trojan",
        "transport": "tcp",
        "security": "tls",
        "flow": "",
        "port": 8443,
        "alpn": "h2,http/1.1",
    },
    {
        "id": "plain-tcp",
        "title": "Без шифрования",
        "badge": "только для теста",
        "hint": "VLESS + TCP без TLS. Годится для локальной проверки, "
                "в интернет такое выставлять нельзя.",
        "protocol": "vless",
        "transport": "tcp",
        "security": "none",
        "flow": "",
        "port": 8080,
    },
)

PRESET_IDS = tuple(preset["id"] for preset in PRESETS)


def preset(preset_id: str) -> dict[str, Any]:
    for item in PRESETS:
        if item["id"] == preset_id:
            return dict(item)
    raise ValueError(f"Неизвестный пресет: {preset_id}")


def supports_vision(protocol: str, transport: str, security: str) -> bool:
    return protocol == "vless" and transport == "tcp" and security in ("reality", "tls")


def validate(data: dict[str, Any]) -> None:
    """Проверить совместимость полей ноды; ValueError — текст для пользователя."""
    protocol = str(data.get("protocol") or "vless")
    transport = str(data.get("transport") or "tcp")
    security = str(data.get("security") or "reality")
    flow = str(data.get("flow") or "")
    if protocol not in PROTOCOLS:
        raise ValueError("Неизвестный протокол")
    if transport not in TRANSPORTS:
        raise ValueError("Неизвестный транспорт")
    if security not in SECURITIES:
        raise ValueError("Неизвестный тип безопасности")
    if security == "reality" and transport not in REALITY_TRANSPORTS:
        raise ValueError(
            f"Reality не работает с транспортом {TRANSPORTS[transport]}: "
            "выберите TCP, gRPC или XHTTP"
        )
    if security == "reality" and protocol == "trojan":
        raise ValueError("Reality не поддерживается для Trojan: нужен Fusion/TLS")
    if protocol == "trojan" and security == "none":
        raise ValueError("Trojan без TLS не имеет смысла — выберите TLS")
    if flow and flow != VISION_FLOW:
        raise ValueError("Неизвестный flow")
    if flow and not supports_vision(protocol, transport, security):
        raise ValueError("xtls-rprx-vision доступен только для VLESS + TCP + TLS/Reality")
    if security in ("reality", "tls") and transport in PATH_TRANSPORTS:
        path = str(data.get("path") or "")
        if path and not path.startswith("/"):
            raise ValueError("Путь должен начинаться со слеша")


def require_sni(data: dict[str, Any]) -> None:
    """Для Reality нужен домен-маскировка; проверяется после авто-заполнения."""
    if str(data.get("security") or "reality") != "reality":
        return
    if not str(data.get("sni") or "").strip():
        raise ValueError("Для Reality укажите SNI — домен-маскировку")


def decorate(data: dict[str, Any]) -> dict[str, Any]:
    """Достроить производные поля ноды перед сохранением."""
    result = dict(data)
    transport = str(result.get("transport") or "tcp")
    security = str(result.get("security") or "reality")
    address = str(result.get("address") or "").strip()
    host = address.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]

    if security in ("reality", "tls") and not str(result.get("sni") or "").strip():
        if security == "tls" and host and not _is_ip(host):
            result["sni"] = host
        else:
            result["sni"] = sni.suggest(host)
    sni_value = str(result.get("sni") or "").strip()
    if sni_value and security in ("reality", "tls"):
        sni.remember(sni_value)

    port = result.get("port") or 443
    if security == "reality" and sni_value and not str(result.get("dest") or "").strip():
        result["dest"] = f"{sni_value}:{port}"

    if transport in PATH_TRANSPORTS and not str(result.get("path") or "").strip():
        result["path"] = "/dfx"
    if transport == "grpc" and not str(result.get("service_name") or "").strip():
        result["service_name"] = "dfxray"
    if security == "tls" and not str(result.get("alpn") or "").strip():
        result["alpn"] = "h2,http/1.1"
    return result


def _is_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(part.isdigit() for part in parts)


def meta() -> dict[str, Any]:
    """Справочник для формы ноды: пресеты, списки, каталог SNI."""
    return {
        "presets": [dict(item) for item in PRESETS],
        "protocols": [{"id": key, "label": label} for key, label in PROTOCOLS.items()],
        "transports": [{"id": key, "label": label} for key, label in TRANSPORTS.items()],
        "securities": [{"id": key, "label": label} for key, label in SECURITIES.items()],
        "reality_transports": list(REALITY_TRANSPORTS),
        "path_transports": list(PATH_TRANSPORTS),
        "vision_flow": VISION_FLOW,
        "sni": sni.catalog(),
        "default_sni": sni.default(),
        "default_port": 443,
    }
