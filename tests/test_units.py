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


class RealityTests(unittest.TestCase):
    """Сканер целей REALITY: разбор целей и оценка пригодности."""

    def test_parse_targets_handles_lists_and_cidr(self):
        from app import reality

        targets = reality.parse_targets("a.example.com, 10.0.0.0/30\nb.example.com:8443")
        hosts = [item.host for item in targets]
        self.assertIn("a.example.com", hosts)
        self.assertIn("b.example.com", hosts)
        self.assertEqual(targets[-1].port, 8443)
        self.assertIn("10.0.0.1", hosts)

    def test_parse_targets_defaults(self):
        from app import reality

        targets = reality.parse_targets("")
        self.assertEqual(len(targets), len(reality.DEFAULT_TARGETS))
        self.assertTrue(all(item.port == 443 for item in targets))

    def test_parse_targets_limits_ip_range(self):
        from app import reality

        targets = reality.parse_targets("10.0.0.1-10.0.0.250", limit=10)
        self.assertEqual(len(targets), 10)

    def test_certificate_matches_wildcard(self):
        from app import reality

        cert = {"san": ["*.example.com"], "subject": "example.com"}
        self.assertTrue(reality.certificate_matches("cdn.example.com", cert))
        self.assertTrue(reality.certificate_matches("example.com", cert))
        self.assertFalse(reality.certificate_matches("other.org", cert))

    def test_probe_classification(self):
        from app import reality

        probe = reality.Probe(target="x:443", host="x", port=443, tls="TLSv1.3", alpn="h2")
        self.assertEqual(probe.to_dict()["status"], "fail")
        ok = reality.Probe(
            target="x:443", host="x", port=443, tls="TLSv1.3", alpn="h2",
            latency_ms=40, cert="x", chain="x",
        )
        self.assertEqual(ok.status, "fail")  # status выставляется только пробой

    def test_scan_manager_job(self):
        from app import reality

        original = reality.probe_target

        def fake_probe(host, port=443, timeout=5.0, **kwargs):
            return reality.Probe(
                target=f"{host}:{port}", host=host, port=port,
                status="ok", tls="TLSv1.3", alpn="h2", latency_ms=12,
            )

        reality.probe_target = fake_probe
        try:
            job = reality.MANAGER.start("one.example.com, two.example.com", timeout=1, workers=2)
            job.thread.join(timeout=10)
            snapshot = job.snapshot()
        finally:
            reality.probe_target = original
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["done"], 2)
        self.assertTrue(all(item["status"] == "ok" for item in snapshot["results"]))


class OutboundConfigTests(unittest.TestCase):
    """Исходящие из панели попадают в конфиг Xray."""

    def test_outbound_configs(self):
        rows = [
            {"tag": "direct", "type": "direct", "enabled": 1},
            {"tag": "socks-de", "type": "socks", "address": "10.0.0.2", "port": 1080,
             "username": "u", "password": "p", "enabled": 1},
            {"tag": "off", "type": "http", "address": "x", "port": 1, "enabled": 0},
        ]
        entries = xray.outbound_configs(rows)
        tags = [item["tag"] for item in entries]
        self.assertEqual(tags, ["direct", "socks-de"])
        socks = entries[1]["settings"]["servers"][0]
        self.assertEqual(socks["address"], "10.0.0.2")
        self.assertEqual(socks["users"][0]["pass"], "p")

    def test_build_config_merges_outbounds(self):
        config = xray.build_config(
            node(security="none", sni="", dest=""),
            [],
            {},
            [{"tag": "socks-de", "type": "socks", "address": "10.0.0.2", "port": 1080,
              "enabled": 1}],
        )
        tags = [item["tag"] for item in config["outbounds"]]
        self.assertEqual(tags, ["direct", "block", "socks-de"])

    def test_default_outbound_moves_first(self):
        config = xray.build_config(
            node(security="none", sni="", dest=""),
            [],
            {"route_default_outbound": "socks-de"},
            [{"tag": "socks-de", "type": "socks", "address": "10.0.0.2", "port": 1080,
              "enabled": 1}],
        )
        self.assertEqual(config["outbounds"][0]["tag"], "socks-de")


class UpdateVersionTests(unittest.TestCase):
    def test_is_newer(self):
        from app import updates

        self.assertTrue(updates.is_newer("1.1.0", "1.0.0"))
        self.assertTrue(updates.is_newer("v1.0.1", "1.0.0"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.9.9", "1.0.0"))

    def test_version_tuple(self):
        from app import updates

        self.assertEqual(updates._version_tuple("v1.2.3"), (1, 2, 3))
        self.assertEqual(updates._version_tuple("main"), ())


class SelfUpdateTests(unittest.TestCase):
    """Самообновление кода панели из GitHub-архива."""

    def test_self_update_replaces_code_only(self):
        import os
        import pathlib
        import shutil
        import tarfile
        import tempfile

        from app import updates

        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp, "repo-main")
            (src / "app").mkdir(parents=True)
            (src / "app" / "config.py").write_text("VERSION = '9.9.9'\n", encoding="utf-8")
            (src / "static").mkdir()
            (src / "static" / "df.css").write_text("body{}\n", encoding="utf-8")
            (src / ".env").write_text("DFX_ADMIN_PASSWORD=keep-me\n", encoding="utf-8")
            (src / "secrets.txt").write_text("nope\n", encoding="utf-8")
            archive = pathlib.Path(tmp, "src.tar.gz")
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(src, arcname="repo-main")

            target = pathlib.Path(tmp, "target")
            (target / "app").mkdir(parents=True)
            (target / ".env").write_text("DFX_ADMIN_PASSWORD=stay\n", encoding="utf-8")

            original = updates._download
            updates._download = lambda url, dest, timeout=0: shutil.copyfile(archive, dest)
            try:
                result = updates.self_update(ref="main", target=str(target))
            finally:
                updates._download = original

            self.assertTrue(result["ok"], result)
            self.assertEqual((target / "app" / "config.py").read_text(encoding="utf-8"), "VERSION = '9.9.9'\n")
            self.assertTrue((target / "static" / "df.css").exists())
            self.assertEqual((target / ".env").read_text(encoding="utf-8"), "DFX_ADMIN_PASSWORD=stay\n")
            self.assertFalse((target / "secrets.txt").exists())
            self.assertEqual(os.path.basename(result["target"]), "target")

    def test_self_capability(self):
        import os
        import pathlib
        import tempfile

        from app import updates

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "app").mkdir()
            os.environ["DFX_SELF_DIR"] = tmp
            updates.SELF_TARGET = tmp
            try:
                os.environ.pop("DFX_SELF_UPDATE", None)
                self.assertFalse(updates.self_capable())
                os.environ["DFX_SELF_UPDATE"] = "1"
                self.assertTrue(updates.self_capable())
                cap = updates.capability()
                self.assertEqual(cap["mode"], "self")
                self.assertIn("self-update", cap["command"])
            finally:
                os.environ.pop("DFX_SELF_UPDATE", None)


class MigrationTests(unittest.TestCase):
    """Миграция старой базы до схемы с метриками серверов."""

    def test_v3_migration_adds_node_columns(self):
        import sqlite3

        from app import db

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE groups (id INTEGER PRIMARY KEY);
            CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE traffic (user_id INTEGER, node_id INTEGER, day TEXT, up INTEGER, down INTEGER);
            INSERT INTO nodes (name) VALUES ('old node');
            """
        )
        db._migrate(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(nodes)")}
        for expected in ("region", "install_token", "agent_version", "xray_running",
                         "uptime_seconds", "load1", "cfg_revision", "last_error"):
            self.assertIn(expected, columns)
        token = conn.execute("SELECT install_token FROM nodes").fetchone()[0]
        self.assertTrue(token)
