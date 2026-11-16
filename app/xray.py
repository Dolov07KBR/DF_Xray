"""Генерация конфигов Xray, клиентских ссылок и Reality-ключей.

Модуль ничего не пишет в БД: на вход получает строки нод/пользователей,
на выход — dict, который можно отдать агенту ноды или показать в панели.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
from collections.abc import Iterable
from typing import Any

from .utils import b64url, to_bool, to_int

API_PORT = 10085
API_LISTEN = f"127.0.0.1:{API_PORT}"
#: Имена транспортов Xray. h2 (HTTP/2) удалён из ядра — использовать httpupgrade/xhttp.
#: Имена, которые понимают все версии Xray (современные алиасы: raw/websocket).
TRANSPORTS = {"tcp", "ws", "grpc", "xhttp", "httpupgrade"}
#: ALPN по умолчанию: gRPC живёт только на h2, WebSocket/HTTPUpgrade — только на http/1.1.
TRANSPORT_ALPN = {
    "grpc": ["h2"],
    "ws": ["http/1.1"],
    "httpupgrade": ["http/1.1"],
    "xhttp": ["h2"],
}
DEFAULT_ALPN = ["h2", "http/1.1"]
DNS_PRESETS = {
    "cloudflare": ["1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"],
    "google": ["8.8.8.8", "8.8.4.4", "2001:4860:4860::8888"],
    "quad9": ["9.9.9.9", "149.112.112.112"],
    "system": [],
}


def _truthy(value: Any) -> bool:
    return to_bool(value)


def _get(row: Any, key: str, default: Any = None) -> Any:
    """Достать поле из sqlite3.Row или dict."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def user_email(user: Any) -> str:
    """Стабильный идентификатор для статистики Xray (user>>>email>>>traffic)."""
    return str(user["username"])


VISION_FLOW = "xtls-rprx-vision"


def effective_flow(node: Any, user: Any) -> str:
    """flow поддерживается только для VLESS + TCP + TLS/Reality и только Vision.

    Xray 25.x принимает единственное значение ``xtls-rprx-vision`` (все прежние
    ``xtls-rprx-direct`` и подобные удалены), а на WS/gRPC/XHTTP flow запрещён —
    конфиг с ним не поднимется.
    """
    if (_get(node, "protocol") or "vless") != "vless":
        return ""
    if (_get(node, "transport") or "tcp") != "tcp":
        return ""
    if (_get(node, "security") or "none") not in ("reality", "tls"):
        return ""
    flow = (_get(user, "flow") or _get(node, "flow") or "").strip()
    return VISION_FLOW if flow == VISION_FLOW else ""


def client_entry(node: Any, user: Any) -> dict[str, Any]:
    """Клиент inbound'а в том виде, в каком его понимает Xray.

    Поля ``limitIp`` в Xray нет (это расширение XrayR/3x-ui) — лимит устройств
    панель считает сама, поэтому в конфиг он не попадает.
    """
    protocol = (_get(node, "protocol") or "vless").lower()
    email = user_email(user)
    if protocol == "trojan":
        client: dict[str, Any] = {"password": user["uuid"], "email": email}
    elif protocol == "vmess":
        client = {"id": user["uuid"], "email": email, "alterId": 0, "security": "auto"}
    else:
        client = {"id": user["uuid"], "email": email}
        flow = effective_flow(node, user)
        if flow:
            client["flow"] = flow
    return client


def transport_alpn(transport: str) -> list[str]:
    """ALPN по умолчанию для TLS: gRPC требует h2 первым, WebSocket — только http/1.1."""
    return list(TRANSPORT_ALPN.get((transport or "tcp").lower(), DEFAULT_ALPN))


def effective_alpn(node: Any) -> list[str]:
    """ALPN ноды с поправкой на транспорт (gRPC всегда h2, WebSocket — http/1.1)."""
    transport = (_get(node, "transport") or "tcp").lower()
    raw = [a.strip() for a in str(_get(node, "alpn") or "").split(",") if a.strip()]
    if transport == "grpc":
        return ["h2"]
    if transport in ("ws", "httpupgrade"):
        return ["http/1.1"]
    return raw or transport_alpn(transport)


def split_short_ids(value: Any) -> list[str]:
    return [s.strip() for s in str(value or "").split(",") if s.strip()]


def normalize_short_id(value: str) -> str:
    """shortId в REALITY — чётное число hex-символов, до 16 штук."""
    cleaned = (value or "").strip().lower()
    if cleaned and (len(cleaned) > 16 or any(c not in "0123456789abcdef" for c in cleaned)):
        raise ValueError(f"shortId «{value}» должен состоять из hex-цифр (до 16 символов)")
    if cleaned and len(cleaned) % 2:
        raise ValueError(f"shortId «{value}» должен иметь чётное число hex-символов")
    return cleaned


def _stream_settings(node: Any) -> dict[str, Any]:
    transport = (_get(node, "transport") or "tcp").lower()
    security = (_get(node, "security") or "none").lower()
    sni = (_get(node, "sni") or "").strip()
    path = (_get(node, "path") or "").strip() or "/"
    stream: dict[str, Any] = {"network": transport}

    if transport == "ws":
        ws: dict[str, Any] = {"path": path}
        if sni:
            # На сервере host — проверка заголовка Host у клиента (headers — только клиентские).
            ws["host"] = sni
        stream["wsSettings"] = ws
    elif transport == "httpupgrade":
        hu: dict[str, Any] = {"path": path}
        if sni:
            hu["host"] = sni
        stream["httpupgradeSettings"] = hu
    elif transport == "grpc":
        stream["grpcSettings"] = {
            "serviceName": (_get(node, "service_name") or "dfxray").strip() or "dfxray",
            "multiMode": False,
        }
    elif transport == "xhttp":
        stream["xhttpSettings"] = {
            "path": path,
            "mode": "auto",
        }
    else:
        stream["tcpSettings"] = {"header": {"type": "none"}}

    if security == "reality":
        dest = (_get(node, "dest") or "").strip() or f"{sni or 'www.microsoft.com'}:443"
        short_ids = [normalize_short_id(s) for s in split_short_ids(_get(node, "short_id"))] or [""]
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "show": False,
            "target": dest,
            "xver": 0,
            "serverNames": [sni] if sni else ["www.microsoft.com"],
            "privateKey": _get(node, "private_key") or "",
            "shortIds": short_ids,
        }
    elif security == "tls":
        stream["security"] = "tls"
        stream["tlsSettings"] = {
            "alpn": effective_alpn(node),
            "minVersion": "1.2",
            "certificates": [
                {
                    "certificateFile": _get(node, "cert_file") or "/etc/xray/cert/fullchain.pem",
                    "keyFile": _get(node, "key_file") or "/etc/xray/cert/privkey.pem",
                }
            ],
        }
    else:
        stream["security"] = "none"
    return stream


def node_inbound(node: Any, users: Iterable[Any]) -> dict[str, Any]:
    protocol = (_get(node, "protocol") or "vless").lower()
    clients = [client_entry(node, user) for user in users]
    if protocol == "vless":
        settings: dict[str, Any] = {"clients": clients, "decryption": "none"}
    elif protocol == "vmess":
        settings = {"clients": clients}
    else:
        settings = {"clients": clients}
    inbound = {
        "tag": f"node-{_get(node, 'id')}-{protocol}",
        "listen": "0.0.0.0",
        "port": to_int(_get(node, "port"), 443),
        "protocol": protocol,
        "settings": settings,
        "streamSettings": _stream_settings(node),
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
            "routeOnly": True,
        },
    }
    if protocol == "trojan":
        inbound["settings"]["fallbacks"] = []
    return inbound


def api_object() -> dict[str, Any]:
    """API статистики Xray. Упрощённый режим (Xray ≥ 1.8.12): listen прямо в api."""
    return {
        "tag": "api",
        "listen": API_LISTEN,
        "services": ["HandlerService", "StatsService"],
    }


def _routing(settings: dict[str, str]) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    if _truthy(settings.get("block_bittorrent")):
        rules.append(
            {"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"}
        )
    if _truthy(settings.get("block_ads")):
        rules.append(
            {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"}
        )
    if _truthy(settings.get("block_private")):
        rules.append({"type": "field", "ip": ["geoip:private"], "outboundTag": "block"})
    if _truthy(settings.get("route_ru_direct")):
        rules.append(
            {
                "type": "field",
                "domain": ["geosite:category-ru", "domain:ru"],
                "outboundTag": "direct",
            }
        )
        rules.append({"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"})
    return {"domainStrategy": "IPIfNonMatch", "rules": rules}



# --------------------------------------------------------------------------
# Исходящие (outbounds) из панели
# --------------------------------------------------------------------------


def outbound_configs(rows: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Превратить записи outbounds из БД в блоки конфига Xray."""
    result: list[dict[str, Any]] = []
    for row in rows or ():
        data = dict(row)
        if not to_bool(data.get("enabled", True)):
            continue
        kind = (data.get("type") or "direct").lower()
        tag = (data.get("tag") or "out").strip() or "out"
        address = (data.get("address") or "").strip()
        port = to_int(data.get("port"))
        if kind == "direct":
            entry = {"tag": tag, "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4v6"}}
        elif kind == "block":
            entry = {"tag": tag, "protocol": "blackhole", "settings": {}}
        elif kind in ("socks", "http"):
            server: dict[str, Any] = {"address": address or "127.0.0.1", "port": port or 1080}
            if data.get("username"):
                server["users"] = [
                    {"user": data.get("username") or "", "pass": data.get("password") or ""}
                ]
            entry = {"tag": tag, "protocol": kind, "settings": {"servers": [server]}}
        elif kind == "shadowsocks":
            server = {
                "address": address or "127.0.0.1",
                "port": port or 8388,
                "method": "aes-256-gcm",
                "password": data.get("password") or "",
            }
            entry = {"tag": tag, "protocol": "shadowsocks", "settings": {"servers": [server]}}
        elif kind == "trojan":
            server = {
                "address": address or "127.0.0.1",
                "port": port or 443,
                "password": data.get("password") or "",
            }
            if data.get("sni"):
                server["sni"] = data["sni"]
            entry = {"tag": tag, "protocol": "trojan", "settings": {"servers": [server]}}
        else:
            continue
        result.append(entry)
    return result


def _merge_outbounds(defaults: list[dict[str, Any]], extra: list[dict[str, Any]],
                     primary: str = "") -> list[dict[str, Any]]:
    merged = list(defaults)
    known = {item["tag"] for item in merged}
    for item in extra:
        if item["tag"] in known:
            continue
        merged.append(item)
        known.add(item["tag"])
    if primary:
        for index, item in enumerate(merged):
            if item["tag"] == primary and index:
                merged.insert(0, merged.pop(index))
                break
    return merged


def build_config(
    node: Any,
    users: Iterable[Any],
    settings: dict[str, str] | None = None,
    outbounds: Iterable[Any] | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    dns_servers = DNS_PRESETS.get(settings.get("dns_preset", "cloudflare"), [])
    dns: dict[str, Any] = {"servers": dns_servers or ["localhost"]}
    if dns_servers:
        dns["queryStrategy"] = "UseIPv4"

    config: dict[str, Any] = {
        "log": {"loglevel": "warning", "access": "none"},
        "dns": dns,
        "inbounds": [node_inbound(node, users)],
        "outbounds": _merge_outbounds(
            [
                {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4v6"}},
                {"tag": "block", "protocol": "blackhole", "settings": {}},
            ],
            outbound_configs(outbounds),
            (settings.get("route_default_outbound") or "").strip(),
        ),
        "routing": _routing(settings),
        "stats": {},
        "policy": {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True,
                    "handshake": 4,
                    "connIdle": 300,
                    "uplinkOnly": 2,
                    "downlinkOnly": 5,
                    "bufferSize": 512,
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True,
                "statsOutboundUplink": True,
                "statsOutboundDownlink": True,
            },
        },
        "api": api_object(),
    }
    return config


# --------------------------------------------------------------------------
# Клиентские ссылки
# --------------------------------------------------------------------------


def _fragment(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def _query(params: dict[str, Any]) -> str:
    clean = {k: str(v) for k, v in params.items() if v not in (None, "", False)}
    return urllib.parse.urlencode(clean, quote_via=urllib.parse.quote, safe="")


def build_link(node: Any, user: Any, panel_title: str = "DF_Xray") -> str:
    protocol = (_get(node, "protocol") or "vless").lower()
    address = _get(node, "address") or ""
    port = to_int(_get(node, "port"), 443)
    transport = (_get(node, "transport") or "tcp").lower()
    security = (_get(node, "security") or "none").lower()
    sni = (_get(node, "sni") or "").strip()
    if not sni and security == "tls":
        sni = address
    fingerprint = (_get(node, "fingerprint") or "chrome").strip()
    path = (_get(node, "path") or "/") or "/"
    service_name = (_get(node, "service_name") or "dfxray").strip() or "dfxray"
    alpn = [] if security == "reality" else effective_alpn(node)
    label = f"{user['username']} · {_get(node, 'name') or address} · {panel_title}"
    frag = _fragment(label)

    common_net: dict[str, Any] = {"type": transport}
    if transport == "ws":
        common_net["path"] = path
        if sni:
            common_net["host"] = sni
    elif transport == "grpc":
        common_net["serviceName"] = service_name
        common_net["mode"] = "gun"
    elif transport == "xhttp":
        common_net["path"] = path
        common_net["mode"] = "auto"
        if sni:
            common_net["host"] = sni
    elif transport == "httpupgrade":
        common_net["path"] = path
        if sni:
            common_net["host"] = sni

    if protocol == "vmess":
        http_like = transport in ("ws", "xhttp", "httpupgrade")
        payload = {
            "v": "2",
            "ps": label,
            "add": address,
            "port": str(port),
            "id": user["uuid"],
            "aid": "0",
            "scy": "auto",
            "net": "ws" if transport == "ws" else transport,
            "type": "gun" if transport == "grpc" else "none",
            "host": sni if http_like else "",
            "path": path if http_like else "",
            "tls": security if security in ("tls", "reality") else "",
            "sni": sni if security in ("tls", "reality") else "",
            "alpn": ",".join(alpn) if security == "tls" else "",
            "fp": fingerprint if security in ("tls", "reality") else "",
        }
        if transport == "grpc":
            payload["path"] = service_name
        if transport == "xhttp":
            payload["type"] = "auto"
        if security == "reality":
            payload["pbk"] = _get(node, "public_key") or ""
            payload["sid"] = (_get(node, "short_id") or "").split(",")[0].strip()
            payload["spx"] = "/"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return "vmess://" + base64.b64encode(raw).decode()

    if security == "reality":
        params = {
            "encryption": "none",
            "security": "reality",
            "sni": sni,
            "fp": fingerprint,
            "pbk": _get(node, "public_key") or "",
            "sid": (_get(node, "short_id") or "").split(",")[0].strip(),
            "spx": "/",
            **common_net,
        }
        if effective_flow(node, user):
            params["flow"] = effective_flow(node, user)
        if protocol == "trojan":
            return f"trojan://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"
        return f"vless://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"

    if security == "tls":
        params = {
            "encryption": "none",
            "security": "tls",
            "sni": sni,
            "fp": fingerprint,
            "alpn": ",".join(alpn),
            **common_net,
        }
        if effective_flow(node, user):
            params["flow"] = effective_flow(node, user)
        if protocol == "trojan":
            return f"trojan://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"
        return f"vless://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"

    params = {"encryption": "none", "security": "none", **common_net}
    if protocol == "trojan":
        return f"trojan://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"
    return f"vless://{user['uuid']}@{address}:{port}?{_query(params)}#{frag}"


def build_links(
    user: Any, nodes: Iterable[Any], panel_title: str = "DF_Xray"
) -> list[dict[str, Any]]:
    allowed = {
        int(x) for x in str(user["node_ids"] or "").split(",") if x.strip().isdigit()
    }
    links: list[dict[str, Any]] = []
    for node in nodes:
        if not node["enabled"]:
            continue
        node_keys = node.keys() if hasattr(node, "keys") else ()
        if node["drain"] if "drain" in node_keys else 0:
            # Drain: сервер дорабатывает текущих клиентов, но в новые подписки не попадает.
            continue
        if allowed and int(node["id"]) not in allowed:
            continue
        links.append(
            {
                "node_id": node["id"],
                "node_name": node["name"],
                "protocol": node["protocol"],
                "transport": node["transport"],
                "security": node["security"],
                "address": node["address"],
                "port": node["port"],
                "link": build_link(node, user, panel_title),
            }
        )
    return links


def subscription_text(links: list[str]) -> str:
    return base64.b64encode("\n".join(links).encode("utf-8")).decode("ascii")


# --------------------------------------------------------------------------
# Reality-ключи (X25519)
# --------------------------------------------------------------------------


def _der_tail(raw: bytes, size: int = 32) -> bytes:
    return raw[-size:]


def generate_reality_keypair() -> tuple[str, str]:
    """Сгенерировать пару x25519 через openssl (как `xray x25519`)."""
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "openssl не найден в системе. Сгенерируйте ключи командой "
            "`xray x25519` и впишите их вручную."
        )
    with tempfile.TemporaryDirectory() as tmp:
        key_path = os.path.join(tmp, "reality.pem")
        der_path = os.path.join(tmp, "reality.der")
        try:
            subprocess.run(
                [openssl, "genpkey", "-algorithm", "X25519", "-out", key_path],
                check=True,
                capture_output=True,
                timeout=20,
            )
            subprocess.run(
                [openssl, "pkey", "-in", key_path, "-outform", "DER", "-out", der_path],
                check=True,
                capture_output=True,
                timeout=20,
            )
            with open(der_path, "rb") as handle:
                private_raw = handle.read()
            pub_der = subprocess.run(
                [openssl, "pkey", "-in", key_path, "-pubout", "-outform", "DER"],
                check=True,
                capture_output=True,
                timeout=20,
            ).stdout
        except (subprocess.SubprocessError, OSError) as exc:
            raise RuntimeError(f"Не удалось сгенерировать ключи: {exc}") from exc
    private_key = b64url(_der_tail(private_raw))
    public_key = b64url(_der_tail(pub_der))
    return private_key, public_key


# --------------------------------------------------------------------------
# Проверка доступности ноды
# --------------------------------------------------------------------------


def probe(address: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((address, to_int(port, 443)), timeout=timeout):
            latency = round((time.perf_counter() - started) * 1000, 1)
            return {"ok": True, "latency_ms": latency, "error": ""}
    except OSError as exc:
        return {"ok": False, "latency_ms": None, "error": str(exc)}
