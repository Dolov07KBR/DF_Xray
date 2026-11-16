"""Тесты корректности протоколов: конфиг Xray и клиентские ссылки.

Проверяем то, на чём ломаются реальные подключения: ALPN у gRPC/WebSocket,
удалённый транспорт HTTP/2, обязательные поля REALITY, формат ссылок.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import nodecfg, xray, xraycheck

USER = {
    "id": 1,
    "username": "client1",
    "uuid": "11111111-2222-3333-4444-555555555555",
    "flow": "",
    "device_limit": 0,
    "node_ids": "",
    "enabled": 1,
}


def make_node(**overrides):
    node = {
        "id": 1,
        "name": "Server",
        "address": "srv.example.com",
        "region": "RU",
        "port": 443,
        "protocol": "vless",
        "transport": "tcp",
        "security": "reality",
        "sni": "www.microsoft.com",
        "fingerprint": "chrome",
        "private_key": "PRIVATEKEYPRIVATEKEYPRIVATEKEY00",
        "public_key": "PUBLICKEYPUBLICKEYPUBLICKEY000",
        "short_id": "0123456789abcdef",
        "dest": "",
        "path": "",
        "service_name": "",
        "flow": nodecfg.VISION_FLOW,
        "alpn": "",
        "cert_file": "",
        "key_file": "",
        "enabled": 1,
        "drain": 0,
    }
    node.update(overrides)
    return node


def build(node, user=None):
    return xray.build_config(node, [user or USER], {}, [])


class ProtocolMatrixTests(unittest.TestCase):
    """Каждый пресет должен давать конфиг, который примет Xray."""

    def test_presets_produce_valid_config(self):
        for preset in nodecfg.PRESETS:
            with self.subTest(preset=preset["id"]):
                node = make_node(**{k: v for k, v in preset.items() if k in make_node()})
                node["security"] = preset["security"]
                if preset["security"] == "tls":
                    node["cert_file"] = "/etc/xray/cert/fullchain.pem"
                    node["key_file"] = "/etc/xray/cert/privkey.pem"
                problems = xraycheck.validate_config(build(node))
                self.assertEqual(problems, [], f"{preset['id']}: {problems}")

    def test_all_transport_security_pairs(self):
        pairs = [
            ("vless", "tcp", "reality"),
            ("vless", "tcp", "tls"),
            ("vless", "tcp", "none"),
            ("vless", "ws", "tls"),
            ("vless", "ws", "none"),
            ("vless", "grpc", "tls"),
            ("vless", "grpc", "reality"),
            ("vless", "xhttp", "reality"),
            ("vless", "xhttp", "tls"),
            ("vless", "httpupgrade", "tls"),
            ("vmess", "ws", "tls"),
            ("vmess", "tcp", "tls"),
            ("trojan", "tcp", "tls"),
            ("trojan", "ws", "tls"),
        ]
        for protocol, transport, security in pairs:
            with self.subTest(protocol=protocol, transport=transport, security=security):
                node = make_node(
                    protocol=protocol,
                    transport=transport,
                    security=security,
                    flow=nodecfg.VISION_FLOW if nodecfg.supports_vision(protocol, transport, security) else "",
                    path="/p" if transport in nodecfg.PATH_TRANSPORTS else "",
                    service_name="dfxray" if transport == "grpc" else "",
                    alpn=nodecfg.TRANSPORT_ALPN.get(transport, ""),
                )
                nodecfg.validate(node)
                problems = xraycheck.validate_config(build(node))
                self.assertEqual(problems, [], f"{protocol}/{transport}/{security}: {problems}")


class AlpnTests(unittest.TestCase):
    def test_grpc_tls_uses_h2_first(self):
        node = make_node(protocol="vless", transport="grpc", security="tls", flow="",
                         service_name="dfxray", alpn="http/1.1,h2")
        stream = xray._stream_settings(node)
        self.assertEqual(stream["tlsSettings"]["alpn"], ["h2"])

    def test_ws_tls_uses_http11(self):
        node = make_node(transport="ws", security="tls", flow="", path="/ws", alpn="h2,http/1.1")
        stream = xray._stream_settings(node)
        self.assertEqual(stream["tlsSettings"]["alpn"], ["http/1.1"])

    def test_alpn_validated(self):
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "vless", "transport": "ws", "security": "tls", "alpn": "h2,http/1.1"})
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "vless", "transport": "grpc", "security": "tls", "alpn": "http/1.1"})


class TransportTests(unittest.TestCase):
    def test_http2_transport_is_gone(self):
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "vless", "transport": "h2", "security": "tls"})
        self.assertNotIn("h2", nodecfg.TRANSPORTS)

    def test_httpupgrade_supported(self):
        nodecfg.validate({"protocol": "vless", "transport": "httpupgrade", "security": "tls", "path": "/up"})
        node = make_node(transport="httpupgrade", security="tls", flow="", path="/up")
        stream = xray._stream_settings(node)
        self.assertEqual(stream["network"], "httpupgrade")
        self.assertEqual(stream["httpupgradeSettings"]["path"], "/up")

    def test_reality_restrictions(self):
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "vless", "transport": "ws", "security": "reality"})
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "vmess", "transport": "tcp", "security": "reality"})
        with self.assertRaises(ValueError):
            nodecfg.validate({"protocol": "trojan", "transport": "tcp", "security": "reality"})

    def test_reality_requires_sni_and_keys(self):
        nodecfg.require_sni({"security": "reality", "sni": "www.microsoft.com"})
        with self.assertRaises(ValueError):
            nodecfg.require_sni({"security": "reality", "sni": ""})
        node = make_node(private_key="", short_id="")
        problems = xraycheck.validate_config(build(node))
        self.assertTrue(any("privateKey" in p for p in problems))

    def test_short_id_validation(self):
        self.assertEqual(xray.normalize_short_id("aabb"), "aabb")
        with self.assertRaises(ValueError):
            xray.normalize_short_id("abc")
        with self.assertRaises(ValueError):
            xray.normalize_short_id("zzzz")
        self.assertFalse(xraycheck.is_valid_short_id("abc"))
        self.assertTrue(xraycheck.is_valid_short_id(""))


class LinksTests(unittest.TestCase):
    def _parse(self, link):
        parsed = urllib.parse.urlsplit(link)
        return parsed, urllib.parse.parse_qs(parsed.query)

    def test_ws_tls_link(self):
        node = make_node(transport="ws", security="tls", flow="", path="/dfws", sni="node.example.com")
        link = xray.build_link(node, USER)
        _, params = self._parse(link)
        self.assertEqual(params["type"], ["ws"])
        self.assertEqual(params["alpn"], ["http/1.1"])
        self.assertEqual(params["path"], ["/dfws"])
        self.assertEqual(params["host"], ["node.example.com"])
        self.assertEqual(params["security"], ["tls"])

    def test_reality_vision_link(self):
        node = make_node()
        link = xray.build_link(node, USER)
        _, params = self._parse(link)
        self.assertEqual(params["security"], ["reality"])
        self.assertEqual(params["pbk"], [node["public_key"]])
        self.assertEqual(params["sid"], ["0123456789abcdef"])
        self.assertEqual(params["flow"], [nodecfg.VISION_FLOW])
        self.assertNotIn("alpn", params)

    def test_grpc_link(self):
        node = make_node(transport="grpc", security="tls", flow="", service_name="mygrpc")
        link = xray.build_link(node, USER)
        _, params = self._parse(link)
        self.assertEqual(params["type"], ["grpc"])
        self.assertEqual(params["serviceName"], ["mygrpc"])
        self.assertEqual(params["mode"], ["gun"])
        self.assertEqual(params["alpn"], ["h2"])

    def test_vmess_grpc_link(self):
        node = make_node(protocol="vmess", transport="grpc", security="tls", flow="", service_name="vmgrpc")
        link = xray.build_link(node, USER)
        payload = json.loads(base64.b64decode(link[len("vmess://"):]))
        self.assertEqual(payload["net"], "grpc")
        self.assertEqual(payload["type"], "gun")
        self.assertEqual(payload["path"], "vmgrpc")
        self.assertEqual(payload["tls"], "tls")

    def test_flow_only_for_vision(self):
        node = make_node(transport="ws", security="tls", flow="", path="/x")
        link = xray.build_link(node, {**USER, "flow": nodecfg.VISION_FLOW})
        _, params = self._parse(link)
        self.assertNotIn("flow", params)


class SchemaGuardTests(unittest.TestCase):
    """Проверки, которые ловят поля, отсутствующие в Xray (частая причина «не поднимается»)."""

    def test_limit_ip_is_rejected_by_validator(self):
        cfg = xray.build_config(make_node(), [USER])
        cfg["inbounds"][0]["settings"]["clients"][0]["limitIp"] = 3
        self.assertTrue(any("limitIp" in problem for problem in xraycheck.validate_config(cfg)))

    def test_flow_with_ws_transport_is_rejected(self):
        cfg = xray.build_config(make_node(transport="ws", security="tls", path="/ws"), [USER])
        cfg["inbounds"][0]["settings"]["clients"][0]["flow"] = nodecfg.VISION_FLOW
        self.assertTrue(
            any("транспортом ws" in problem for problem in xraycheck.validate_config(cfg))
        )

    def test_unknown_certificate_field(self):
        cfg = xray.build_config(make_node(security="tls"), [USER])
        cfg["inbounds"][0]["streamSettings"]["tlsSettings"]["certificates"][0]["certPath"] = "/x"
        self.assertTrue(
            any("certPath" in problem for problem in xraycheck.validate_config(cfg))
        )

    def test_reality_server_has_no_client_fields(self):
        reality = xray.build_config(make_node(), [USER])["inbounds"][0]["streamSettings"]["realitySettings"]
        for field in ("spiderX", "publicKey", "shortId"):
            self.assertNotIn(field, reality)


if __name__ == "__main__":
    unittest.main()
