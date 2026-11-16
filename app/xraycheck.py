"""Проверка конфига Xray по фактической схеме ядра.

Модуль не запускает Xray, а сверяет собранный панелью JSON с полями и правилами,
которые есть в Xray-core (`infra/conf`). Нужен, чтобы панель не отдавала агенту
конфиг, который ядро отклонит — например, с удалённым транспортом HTTP/2, с
неверным ALPN для gRPC/WebSocket или с Reality без shortId.

Возвращает список проблем: пустой список — конфиг корректен.
"""

from __future__ import annotations

from typing import Any

from app.xray import VISION_FLOW

#: Транспорты, которые понимает ядро. `h2`/`http`/`quic` удалены начиная с Xray 25.x.
NETWORKS = {"tcp", "raw", "ws", "websocket", "grpc", "xhttp", "splithttp", "httpupgrade"}
REMOVED_NETWORKS = {"h2", "http", "h3", "quic"}
SECURITIES = {"none", "tls", "reality"}
REALITY_NETWORKS = {"tcp", "raw", "xhttp", "splithttp", "grpc"}
PROTOCOLS = {"vless", "vmess", "trojan", "shadowsocks", "socks", "http", "dokodemo-door", "tunnel"}

ROOT_KEYS = {
    "log", "dns", "inbounds", "outbounds", "routing", "stats", "policy", "api",
    "observatory", "fakedns", "reverse", "transport", "metrics", "browserForwarder",
}
INBOUND_KEYS = {"tag", "listen", "port", "protocol", "settings", "streamSettings", "sniffing"}
STREAM_KEYS = {
    "network", "method", "security", "tcpSettings", "rawSettings", "wsSettings",
    "grpcSettings", "xhttpSettings", "httpupgradeSettings", "realitySettings",
    "tlsSettings", "sockopt", "finalmask", "kcpSettings", "hysteriaSettings",
    "masqueSettings", "xdriveSettings",
}
# Наборы полей сверены с infra/conf Xray-core (transport_security.go,
# transport_method.go, xray.go) — неизвестные поля Xray молча игнорирует,
# поэтому лучше поймать опечатку в панели, чем искать её на ноде.
TLS_KEYS = {
    "serverName", "alpn", "minVersion", "maxVersion", "certificates", "allowInsecure",
    "cipherSuites", "curvePreferences", "disableSystemRoot", "enableSessionResumption",
    "fingerprint", "masterKeyLog", "echConfigList", "echServerKeys", "echSockopt",
    "pinnedPeerCertSha256", "rejectUnknownSni", "useSystemCA", "verifyPeerCertByName",
}
REALITY_KEYS = {
    "show", "target", "dest", "xver", "serverNames", "privateKey", "shortIds",
    "spiderX", "mldsa65Seed", "mldsa65Verify", "publicKey", "password", "shortId",
    "serverName", "fingerprint", "type", "masterKeyLog", "minClientVer", "maxClientVer",
    "maxTimeDiff", "limitFallbackUpload", "limitFallbackDownload",
}
WS_KEYS = {"path", "host", "headers", "acceptProxyProtocol", "heartbeatPeriod"}
GRPC_KEYS = {
    "serviceName", "multiMode", "authority", "user_agent", "health_check_timeout",
    "idle_timeout", "permit_without_stream", "initial_windows_size",
}
XHTTP_KEYS = {
    "path", "host", "mode", "headers", "extra", "xmux", "downloadSettings", "h2Params",
    "noGRPCHeader", "noSSEHeader", "uplinkHTTPMethod", "seqKey", "seqPlacement",
    "sessionIDKey", "sessionIDLength", "sessionIDPlacement", "sessionIDTable",
    "uplinkChunkSize", "uplinkDataKey", "uplinkDataPlacement", "scMaxEachPostBytes",
    "scMinPostsIntervalMs", "scMaxBufferedPosts", "scStreamUpServerSecs",
    "serverMaxHeaderBytes", "xPaddingBytes", "xPaddingObfsMode", "xPaddingKey",
    "xPaddingHeader", "xPaddingPlacement", "xPaddingMethod",
}
HTTPUPGRADE_KEYS = {"path", "host", "headers", "acceptProxyProtocol"}
CERT_KEYS = {
    "certificateFile", "certificate", "keyFile", "key", "usage", "ocspStapling",
    "oneTimeLoading", "buildChain",
}
SNIFFING_KEYS = {"enabled", "destOverride", "metadataOnly", "routeOnly", "domainsExcluded"}
OUTBOUND_KEYS = {"tag", "protocol", "settings", "streamSettings", "sendThrough", "mux", "proxySettings"}
API_KEYS = {"tag", "listen", "services", "listenAddr"}
POLICY_KEYS = {"levels", "system"}
XHTTP_MODES = {"auto", "packet-up", "stream-up", "stream-one"}
ALPN_ALLOWED = {"h2", "http/1.1", "h3"}


def _err(problems: list[str], path: str, message: str) -> None:
    problems.append(f"{path}: {message}")


def _unknown(problems: list[str], path: str, data: Any, allowed: set[str]) -> None:
    if not isinstance(data, dict):
        _err(problems, path, "ожидался объект")
        return
    for key in data:
        if key not in allowed:
            _err(problems, path, f"неизвестное поле «{key}»")


def is_valid_short_id(value: Any) -> bool:
    text = str(value or "")
    if text == "":
        return True
    if len(text) > 16 or len(text) % 2:
        return False
    return all(char in "0123456789abcdef" for char in text.lower())


def _check_stream(problems: list[str], path: str, stream: Any) -> None:
    if not isinstance(stream, dict):
        _err(problems, path, "отсутствует streamSettings")
        return
    _unknown(problems, path, stream, STREAM_KEYS)
    network = str(stream.get("network") or stream.get("method") or "tcp").lower()
    security = str(stream.get("security") or "none").lower()
    if network in REMOVED_NETWORKS:
        _err(problems, path, f"транспорт «{network}» удалён из Xray — используйте xhttp или httpupgrade")
    elif network not in NETWORKS:
        _err(problems, path, f"неизвестный транспорт «{network}»")
    if security not in SECURITIES:
        _err(problems, path, f"неизвестная безопасность «{security}»")

    if network in {"ws", "websocket"}:
        ws = stream.get("wsSettings") or {}
        _unknown(problems, f"{path}.wsSettings", ws, WS_KEYS)
    elif network == "grpc":
        grpc = stream.get("grpcSettings") or {}
        _unknown(problems, f"{path}.grpcSettings", grpc, GRPC_KEYS)
        if not str(grpc.get("serviceName") or "").strip():
            _err(problems, f"{path}.grpcSettings", "пустой serviceName")
    elif network in {"xhttp", "splithttp"}:
        xhttp = stream.get("xhttpSettings") or {}
        _unknown(problems, f"{path}.xhttpSettings", xhttp, XHTTP_KEYS)
        mode = str(xhttp.get("mode") or "auto")
        if mode not in XHTTP_MODES:
            _err(problems, f"{path}.xhttpSettings", f"неизвестный mode «{mode}»")
    elif network == "httpupgrade":
        _unknown(problems, f"{path}.httpupgradeSettings", stream.get("httpupgradeSettings") or {},
                 HTTPUPGRADE_KEYS)

    if security == "reality":
        if network not in REALITY_NETWORKS:
            _err(problems, path, "REALITY поддерживается только с RAW/TCP, XHTTP и gRPC")
        reality = stream.get("realitySettings")
        if not isinstance(reality, dict):
            _err(problems, f"{path}.realitySettings", "обязателен для Reality")
            return
        _unknown(problems, f"{path}.realitySettings", reality, REALITY_KEYS)
        if not str(reality.get("target") or reality.get("dest") or "").strip():
            _err(problems, f"{path}.realitySettings", "не задан target")
        if not reality.get("serverNames"):
            _err(problems, f"{path}.realitySettings", "пустой serverNames")
        if not str(reality.get("privateKey") or "").strip():
            _err(problems, f"{path}.realitySettings", "пустой privateKey")
        short_ids = reality.get("shortIds")
        if not isinstance(short_ids, list) or not short_ids:
            _err(problems, f"{path}.realitySettings", "нужен непустой shortIds")
        else:
            for sid in short_ids:
                if not is_valid_short_id(sid):
                    _err(problems, f"{path}.realitySettings", f"некорректный shortId «{sid}»")
    elif security == "tls":
        tls = stream.get("tlsSettings") or {}
        _unknown(problems, f"{path}.tlsSettings", tls, TLS_KEYS)
        alpn = [str(a).lower() for a in (tls.get("alpn") or [])]
        for item in alpn:
            if item not in ALPN_ALLOWED:
                _err(problems, f"{path}.tlsSettings", f"неизвестный ALPN «{item}»")
        if network == "grpc" and alpn and alpn[0] != "h2":
            _err(problems, f"{path}.tlsSettings", "для gRPC первым в ALPN должен идти h2")
        if network in {"ws", "websocket", "httpupgrade"} and "h2" in alpn:
            _err(problems, f"{path}.tlsSettings", "WebSocket/HTTPUpgrade работают только по http/1.1")
        certs = tls.get("certificates")
        if not isinstance(certs, list) or not certs:
            _err(problems, f"{path}.tlsSettings", "нет сертификата")
        else:
            for index, cert in enumerate(certs):
                if not isinstance(cert, dict):
                    _err(problems, f"{path}.tlsSettings.certificates[{index}]", "ожидался объект")
                    continue
                _unknown(problems, f"{path}.tlsSettings.certificates[{index}]", cert, CERT_KEYS)
                if not str(cert.get("certificateFile") or cert.get("certificate") or "").strip():
                    _err(problems, f"{path}.tlsSettings.certificates[{index}]", "нет certificateFile")
                if not str(cert.get("keyFile") or cert.get("key") or "").strip():
                    _err(problems, f"{path}.tlsSettings.certificates[{index}]", "нет keyFile")


def _check_inbound(problems: list[str], index: int, inbound: Any) -> str:
    path = f"inbounds[{index}]"
    if not isinstance(inbound, dict):
        _err(problems, path, "ожидался объект")
        return ""
    _unknown(problems, path, inbound, INBOUND_KEYS)
    protocol = str(inbound.get("protocol") or "").lower()
    if protocol not in PROTOCOLS:
        _err(problems, path, f"неизвестный протокол «{protocol}»")
    if not inbound.get("tag"):
        _err(problems, path, "нет tag")
    settings = inbound.get("settings") or {}
    if isinstance(settings, dict):
        if protocol == "vless":
            if str(settings.get("decryption") or "") != "none":
                _err(problems, f"{path}.settings", "для VLESS требуется decryption: none")
            extra = set(settings) - {"clients", "users", "decryption", "fallbacks", "flow", "testseed"}
            for key in extra:
                _err(problems, f"{path}.settings", f"неизвестное поле «{key}»")
        clients = settings.get("clients") or settings.get("users") or []
        if not isinstance(clients, list):
            _err(problems, f"{path}.settings", "clients должен быть списком")
            clients = []
        for client_index, client in enumerate(clients):
            if not isinstance(client, dict):
                _err(problems, f"{path}.settings.clients[{client_index}]", "ожидался объект")
                continue
            allowed = {"id", "email", "flow", "level", "alterId", "security", "password"}
            _unknown(problems, f"{path}.settings.clients[{client_index}]", client, allowed)
            if protocol == "trojan" and not str(client.get("password") or ""):
                _err(problems, f"{path}.settings.clients[{client_index}]", "нет password")
            elif protocol in {"vless", "vmess"} and not str(client.get("id") or ""):
                _err(problems, f"{path}.settings.clients[{client_index}]", "нет id")
            if client.get("flow"):
                if protocol != "vless":
                    _err(problems, f"{path}.settings.clients[{client_index}]", "flow есть только у VLESS")
                else:
                    network = str((inbound.get("streamSettings") or {}).get("network") or "tcp").lower()
                    security = str((inbound.get("streamSettings") or {}).get("security") or "none").lower()
                    if network not in {"tcp", "raw"}:
                        _err(
                            problems,
                            f"{path}.settings.clients[{client_index}]",
                            f"flow нельзя использовать с транспортом {network}",
                        )
                    elif security not in {"tls", "reality"}:
                        _err(
                            problems,
                            f"{path}.settings.clients[{client_index}]",
                            "flow работает только поверх TLS или REALITY",
                        )
                if client["flow"] != VISION_FLOW:
                    _err(
                        problems,
                        f"{path}.settings.clients[{client_index}]",
                        f"flow «{client['flow']}» не поддерживается, нужен {VISION_FLOW}",
                    )
    _check_stream(problems, f"{path}.streamSettings", inbound.get("streamSettings"))
    sniffing = inbound.get("sniffing")
    if sniffing is not None:
        _unknown(problems, f"{path}.sniffing", sniffing, SNIFFING_KEYS)
    return str(inbound.get("tag") or "")


def validate_config(config: Any) -> list[str]:
    """Вернуть список проблем конфига; пустой список — Xray его примет."""
    problems: list[str] = []
    if not isinstance(config, dict):
        return ["config: ожидался объект"]
    _unknown(problems, "config", config, ROOT_KEYS)

    inbounds = config.get("inbounds") or []
    if not isinstance(inbounds, list) or not inbounds:
        _err(problems, "config", "нет ни одного inbound")
        inbounds = []
    tags: set[str] = set()
    for index, inbound in enumerate(inbounds):
        tag = _check_inbound(problems, index, inbound)
        if tag:
            if tag in tags:
                _err(problems, f"inbounds[{index}]", f"дублируется tag «{tag}»")
            tags.add(tag)

    outbounds = config.get("outbounds") or []
    if not isinstance(outbounds, list) or not outbounds:
        _err(problems, "config", "нет ни одного outbound")
        outbounds = []
    out_tags: set[str] = set()
    for index, outbound in enumerate(outbounds):
        path = f"outbounds[{index}]"
        if not isinstance(outbound, dict):
            _err(problems, path, "ожидался объект")
            continue
        _unknown(problems, path, outbound, OUTBOUND_KEYS)
        tag = str(outbound.get("tag") or "")
        if not tag:
            _err(problems, path, "нет tag")
        elif tag in out_tags:
            _err(problems, path, f"дублируется tag «{tag}»")
        out_tags.add(tag)
        protocol = str(outbound.get("protocol") or "").lower()
        if protocol not in {"freedom", "blackhole", "socks", "http", "shadowsocks",
                            "trojan", "vless", "vmess"}:
            _err(problems, path, f"неизвестный протокол «{protocol}»")

    routing = config.get("routing")
    if routing is not None:
        if not isinstance(routing, dict):
            _err(problems, "routing", "ожидался объект")
        else:
            _unknown(problems, "routing", routing, {"domainStrategy", "rules", "balancers"})
            for index, rule in enumerate(routing.get("rules") or []):
                path = f"routing.rules[{index}]"
                if not isinstance(rule, dict):
                    _err(problems, path, "ожидался объект")
                    continue
                _unknown(problems, path, rule, {
                    "type", "domain", "ip", "port", "sourcePort", "network", "source",
                    "user", "inboundTag", "outboundTag", "protocol", "attrs", "balancerTag",
                    "ruleTag", "domainMatcher",
                })
                target = str(rule.get("outboundTag") or "")
                if target and target not in out_tags and target != "api":
                    _err(problems, path, f"правило ссылается на несуществующий outbound «{target}»")
                for inbound_tag in rule.get("inboundTag") or []:
                    if inbound_tag not in tags:
                        _err(problems, path, f"правило ссылается на несуществующий inbound «{inbound_tag}»")

    api = config.get("api")
    if api is not None:
        _unknown(problems, "api", api, API_KEYS)
        listen = str(api.get("listen") or api.get("listenAddr") or "")
        if not listen:
            _err(problems, "api", "нужен listen вида 127.0.0.1:10085")
        elif ":" not in listen:
            _err(problems, "api", "listen должен содержать порт")

    policy = config.get("policy")
    if policy is not None:
        _unknown(problems, "policy", policy, POLICY_KEYS)

    return problems
