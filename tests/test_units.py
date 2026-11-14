"""Юнит-тесты: пароли, QR, ссылки, конфиги, утилиты."""

from __future__ import annotations

import json
import unittest

from app import auth, qr, xray
from app.utils import b64decode, gb_to_bytes, human_size, to_bool, to_int


def node(**overrides):
    base = {
        "id": 7,
        "name": "Test Node",
        "address": "node.example.com",
        "port": 443,
        "protocol": "vless",
        "transport": "tcp",
        "security": "reality",
        "sni": "www.microsoft.com",
        "fingerprint": "chrome",
        "private_key": "PRIVATE_KEY",
        "public_key": "PUBLIC_KEY",
        "short_id": "abcd1234",
        "dest": "www.microsoft.com:443",
        "path": "/ws",
        "service_name": "grpcsvc",
        "flow": "xtls-rprx-vision",
        "alpn": "h2,http/1.1",
        "cert_file": "/etc/xray/cert/fullchain.pem",
        "key_file": "/etc/xray/cert/privkey.pem",
        "enabled": 1,
        "node_ids": "",
    }
    base.update(overrides)
    return base


def user(**overrides):
    base = {
        "id": 1,
        "username": "alex",
        "uuid": "11111111-2222-3333-4444-555555555555",
        "flow": "",
        "device_limit": 2,
        "node_ids": None,
    }
    base.update(overrides)
    return base


class PasswordTests(unittest.TestCase):
    def test_hash_and_verify(self):
        stored = auth.hash_password("correct horse battery staple")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertTrue(auth.verify_password("correct horse battery staple", stored))
        self.assertFalse(auth.verify_password("wrong", stored))

    def test_malformed_hash(self):
        self.assertFalse(auth.verify_password("x", "garbage"))
        self.assertFalse(auth.verify_password("x", "pbkdf2_sha256$1$Zm9v$YmFy"))


class UtilsTests(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(gb_to_bytes(0), 0)
        self.assertEqual(gb_to_bytes("1.5"), 1610612736)
        self.assertEqual(human_size(1536), "1.50 КБ")
        self.assertEqual(to_int("42"), 42)
        self.assertEqual(to_int("oops", 7), 7)
        self.assertTrue(to_bool("yes"))
        self.assertFalse(to_bool("0"))

    def test_base64(self):
        self.assertEqual(b64decode("0J/RgNC40LLQtdGCCg=="), "Привет\n")


class QrTests(unittest.TestCase):
    def test_svg_and_png(self):
        svg = qr.svg("vless://test")
        self.assertIn("<svg", svg)
        self.assertIn("<path", svg)
        png = qr.png("vless://test", scale=4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(qr.svg("a"), qr.svg("b"))

    def test_data_uri(self):
        uri = qr.data_uri("hello")
        self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))


class LinkTests(unittest.TestCase):
    def test_vless_reality_link(self):
        link = xray.build_link(node(), user(), "DF_Xray")
        self.assertTrue(link.startswith("vless://11111111-2222-3333-4444-555555555555@node.example.com:443?"))
        self.assertIn("security=reality", link)
        self.assertIn("pbk=PUBLIC_KEY", link)
        self.assertIn("sid=abcd1234", link)
        self.assertIn("flow=xtls-rprx-vision", link)
        self.assertIn("fp=chrome", link)
        self.assertIn("#alex", link.replace("%20", " "))

    def test_vless_ws_tls_link(self):
        link = xray.build_link(
            node(transport="ws", security="tls", sni="cdn.example.com", flow=""),
            user(),
        )
        self.assertIn("type=ws", link)
        self.assertIn("security=tls", link)
        self.assertIn("path=%2Fws", link)
        self.assertIn("host=cdn.example.com", link)
        self.assertNotIn("flow=", link)

    def test_vmess_link_is_base64_json(self):
        link = xray.build_link(node(protocol="vmess", transport="ws", security="tls"), user())
        self.assertTrue(link.startswith("vmess://"))
        payload = json.loads(__import__("base64").b64decode(link[8:]))
        self.assertEqual(payload["id"], user()["uuid"])
        self.assertEqual(payload["net"], "ws")
        self.assertEqual(payload["tls"], "tls")

    def test_trojan_link(self):
        link = xray.build_link(node(protocol="trojan", transport="grpc", security="tls"), user())
        self.assertTrue(link.startswith("trojan://11111111-2222-3333-4444-555555555555@"))
        self.assertIn("serviceName=grpcsvc", link)

    def test_node_filter(self):
        nodes = [node(id=1), node(id=2)]
        links = xray.build_links(user(node_ids="2"), nodes)
        self.assertEqual([item["node_id"] for item in links], [2])
        links = xray.build_links(user(node_ids=None), nodes)
        self.assertEqual(len(links), 2)

    def test_disabled_node_skipped(self):
        self.assertEqual(xray.build_links(user(), [node(enabled=0)]), [])


class ConfigTests(unittest.TestCase):
    def test_clients_only_active(self):
        users = [user(id=1, username="a"), user(id=2, username="b")]
        config_data = xray.build_config(node(), users, {})
        inbound = config_data["inbounds"][1]
        emails = [client["email"] for client in inbound["settings"]["clients"]]
        self.assertEqual(emails, ["a", "b"])
        self.assertEqual(inbound["settings"]["decryption"], "none")
        self.assertEqual(config_data["inbounds"][0]["port"], xray.API_PORT)

    def test_routing_rules_toggle(self):
        config_data = xray.build_config(node(), [], {"block_bittorrent": "0", "block_private": "0"})
        protocols = [rule.get("protocol") for rule in config_data["routing"]["rules"]]
        self.assertNotIn(["bittorrent"], protocols)
        ips = [rule.get("ip") for rule in config_data["routing"]["rules"]]
        self.assertNotIn(["geoip:private"], ips)

        config_data = xray.build_config(
            node(), [], {"block_bittorrent": "1", "block_ads": "1", "route_ru_direct": "1"}
        )
        rules = config_data["routing"]["rules"]
        self.assertTrue(any(rule.get("domain") == ["geosite:category-ads-all"] for rule in rules))
        self.assertTrue(any(rule.get("ip") == ["geoip:ru"] for rule in rules))

    def test_no_flow_for_ws(self):
        config_data = xray.build_config(node(transport="ws", security="tls"), [user(flow="xtls-rprx-vision")], {})
        client = config_data["inbounds"][1]["settings"]["clients"][0]
        self.assertNotIn("flow", client)

    def test_reality_requires_keys(self):
        config_data = xray.build_config(node(), [])
        reality = config_data["inbounds"][1]["streamSettings"]["realitySettings"]
        self.assertEqual(reality["privateKey"], "PRIVATE_KEY")
        self.assertEqual(reality["shortIds"], ["abcd1234"])
        self.assertEqual(reality["dest"], "www.microsoft.com:443")

    def test_tls_certificates(self):
        config_data = xray.build_config(node(security="tls"), [])
        tls = config_data["inbounds"][1]["streamSettings"]["tlsSettings"]
        self.assertEqual(tls["certificates"][0]["certificateFile"], "/etc/xray/cert/fullchain.pem")
        self.assertEqual(tls["alpn"], ["h2", "http/1.1"])

    def test_device_limit(self):
        config_data = xray.build_config(node(), [user(device_limit=3)], {})
        self.assertEqual(config_data["inbounds"][1]["settings"]["clients"][0]["limitIp"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
