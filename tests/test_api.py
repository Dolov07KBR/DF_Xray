"""Интеграционные тесты панели: живой HTTP-сервер + временная SQLite."""

from __future__ import annotations

import base64
import http.cookiejar
import unittest
import urllib.error
import urllib.request

from harness import PanelHarness  # сначала стенд: он выставляет DFX_* переменные

from app import config, db, totp


def node_inbound(config_data):
    for inbound in config_data["inbounds"]:
        if str(inbound.get("tag", "")).startswith("node-"):
            return inbound
    raise AssertionError("в конфиге нет inbound ноды")


class PanelTestCase(PanelHarness):
    # --- tests ---

    def test_health(self):
        status, headers, data = self.json_request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_requires_auth(self):
        status, headers, data = self.json_request("GET", "/api/users")
        self.assertEqual(status, 401)

    def test_login_flow(self):
        status, headers, data = self.json_request(
            "POST", "/api/auth/login", {"username": "admin", "password": "wrong"}
        )
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "Неверное имя пользователя или пароль")

        self.login()
        self.assertTrue(any(cookie.name == "dfx_session" for cookie in self.jar))

        status, headers, data = self.json_request("GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(data["admin"]["username"], "admin")
        self.assertTrue(data["bootstrap_password"])

    def test_csrf_header_required(self):
        self.login()
        status, headers, body = self.request(
            "POST", "/api/users", {"username": "csrf"}, headers={"X-Requested-With": ""}
        )
        self.assertEqual(status, 403)

    def test_dashboard_and_users(self):
        self.login()
        status, _, dashboard = self.json_request("GET", "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(dashboard["counts"]["total"], 8)
        self.assertGreaterEqual(dashboard["nodes"]["online"], 1)
        self.assertEqual(len(dashboard["traffic"]["series"]), 14)

        status, _, users = self.json_request("GET", "/api/users?status=active")
        self.assertEqual(status, 200)
        self.assertGreater(len(users["items"]), 0)

    def test_create_user_with_links_and_subscription(self):
        self.login()
        status, _, user = self.json_request(
            "POST",
            "/api/users",
            {"username": "tester", "email": "tester@example.com", "days": 10, "limit_gb": 0},
        )
        self.assertEqual(status, 201, user)
        self.assertEqual(user["status"], "active")
        self.assertEqual(len(user["links"]), 3)
        self.assertTrue(user["sub_url"].endswith(user["sub_token"]))
        reality = next(item for item in user["links"] if item["security"] == "reality")
        self.assertIn("pbk=", reality["link"])
        self.assertIn("security=reality", reality["link"])
        self.assertIn("sid=", reality["link"])

        status, headers, body = self.request("GET", f"/sub/{user['sub_token']}")
        self.assertEqual(status, 200)
        decoded = base64.b64decode(body.decode()).decode()
        self.assertEqual(len(decoded.splitlines()), 3)
        self.assertIn("subscription-userinfo", {k.lower() for k in headers})
        self.assertIn("profile-title", {k.lower() for k in headers})

    def test_user_actions(self):
        self.login()
        _, _, user = self.json_request(
            "POST", "/api/users", {"username": "actions", "days": 5, "limit_gb": 2}
        )
        user_id = user["id"]

        status, _, updated = self.json_request(
            "POST", f"/api/users/{user_id}/action", {"action": "disable"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["status"], "disabled")

        status, _, updated = self.json_request(
            "POST", f"/api/users/{user_id}/action", {"action": "reset_traffic"}
        )
        self.assertEqual(updated["used_bytes"], 0)

        status, _, extended = self.json_request(
            "POST", f"/api/users/{user_id}/action", {"action": "extend", "value": 30}
        )
        self.assertGreaterEqual(extended["days_left"], 30)

        status, _, deleted = self.json_request("DELETE", f"/api/users/{user_id}")
        self.assertEqual(status, 200)
        status, _, missing = self.json_request("GET", f"/api/users/{user_id}")
        self.assertEqual(status, 404)

    def test_validation_errors(self):
        self.login()
        status, _, data = self.json_request("POST", "/api/users", {"username": "alex"})
        self.assertEqual(status, 400)
        self.assertIn("уже существует", data["error"])

        status, _, data = self.json_request(
            "PATCH", "/api/settings", {"public_base_url": "example.com"}
        )
        self.assertEqual(status, 400)

    def test_qr_codes(self):
        self.login()
        status, headers, body = self.request("GET", "/api/users/1/qr.svg")
        self.assertEqual(status, 200)
        self.assertIn("svg", headers.get("Content-Type", ""))
        self.assertIn(b"<svg", body)

        status, headers, body = self.request("GET", "/api/users/1/qr?format=png")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_node_config_generation(self):
        self.login()
        status, _, node = self.json_request("GET", "/api/nodes/1")
        self.assertEqual(status, 200)
        config_data = node["config"]
        self.assertTrue(config_data["api"]["listen"].startswith("127.0.0.1:"))
        node_inbound_cfg = node_inbound(config_data)
        self.assertEqual(node_inbound_cfg["protocol"], "vless")
        self.assertEqual(node_inbound_cfg["streamSettings"]["security"], "reality")
        self.assertIn("privateKey", node_inbound_cfg["streamSettings"]["realitySettings"])
        self.assertTrue(node_inbound_cfg["settings"]["clients"])
        self.assertTrue(config_data["api"]["services"])
        self.assertTrue(
            any(rule.get("protocol") == ["bittorrent"] for rule in config_data["routing"]["rules"])
        )

    def test_agent_flow_and_limits(self):
        self.login()
        _, _, node = self.json_request("GET", "/api/nodes/1")
        token = node["agent_token"]

        status, _, bad = self.json_request(
            "GET", "/api/agent/config", headers={"X-Node-Token": "nope"}
        )
        self.assertEqual(status, 401)

        status, _, payload = self.json_request(
            "GET", "/api/agent/config", headers={"X-Node-Token": token}
        )
        self.assertEqual(status, 200)
        self.assertIn("revision", payload)
        self.assertIn("config", payload)

        # пользователь с крошечным лимитом: после отчёта должен уйти в limited
        _, _, user = self.json_request(
            "POST", "/api/users", {"username": "limited_by_agent", "days": 30, "limit_gb": 0.001}
        )
        status, _, report = self.json_request(
            "POST",
            "/api/agent/report",
            {
                "xray_version": "Xray 25.9.11",
                "stats": {
                    "users": {"limited_by_agent": {"up": 1024, "down": 10 * 1024 * 1024}},
                    "node": {"up": 1024, "down": 10 * 1024 * 1024},
                },
            },
            headers={"X-Node-Token": token},
        )
        self.assertEqual(status, 200, report)
        self.assertIn("limited_by_agent", report["blocked"])

        _, _, refreshed = self.json_request("GET", f"/api/users/{user['id']}")
        self.assertEqual(refreshed["status"], "limited")
        self.assertGreater(refreshed["used_bytes"], 0)

        # заблокированный пользователь не попадает в конфиг ноды
        _, _, config_response = self.json_request(
            "GET", "/api/agent/config", headers={"X-Node-Token": token}
        )
        emails = [
            client["email"]
            for client in node_inbound(config_response["config"])["settings"]["clients"]
        ]
        self.assertNotIn("limited_by_agent", emails)

    def test_disabled_user_gets_empty_subscription(self):
        self.login()
        _, _, user = self.json_request(
            "POST", "/api/users", {"username": "offline", "days": 5, "enabled": False}
        )
        status, headers, body = self.request("GET", f"/sub/{user['sub_token']}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("x-dfxray-status"), "disabled")

    def test_subscription_page_renders(self):
        self.login()
        _, _, user = self.json_request(
            "POST", "/api/users", {"username": "pageuser", "days": 5}
        )
        status, headers, body = self.request("GET", f"/sub/{user['sub_token']}/page")
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("pageuser", page)
        self.assertIn("QR-код", page)
        self.assertIn("/qr.svg", page)

    def test_public_base_url_setting(self):
        self.login()
        status, _, data = self.json_request(
            "PATCH", "/api/settings", {"public_base_url": "https://panel.example.com"}
        )
        self.assertEqual(status, 200)
        _, _, settings = self.json_request("GET", "/api/settings")
        self.assertEqual(settings["public_base_url"], "https://panel.example.com")
        _, _, user = self.json_request(
            "POST", "/api/users", {"username": "bases", "days": 5}
        )
        self.assertTrue(user["sub_url"].startswith("https://panel.example.com/sub/"))
        # вернуть как было
        self.json_request("PATCH", "/api/settings", {"public_base_url": ""})

    def test_password_change_and_sessions(self):
        self.login()
        status, _, data = self.json_request(
            "POST",
            "/api/account/password",
            {"current_password": "sup3r-secret-pass", "new_password": "new-pass-12345"},
        )
        self.assertEqual(status, 200, data)
        status, _, me = self.json_request("GET", "/api/me")
        self.assertEqual(status, 200)
        # смена пароля закрывает остальные сессии, но текущая продолжает работать
        self.login(password="new-pass-12345")
        # возвращаем исходный пароль, чтобы не мешать остальным тестам
        status, _, data = self.json_request(
            "POST",
            "/api/account/password",
            {"current_password": "new-pass-12345", "new_password": "sup3r-secret-pass"},
        )
        self.assertEqual(status, 200, data)

    def test_backup_download(self):
        self.login()
        status, headers, body = self.request("GET", "/api/maintenance/backup")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"SQLite format 3"))

    # --- группы, исходящие, хосты, документация, обновления ---

    def test_groups_crud(self):
        self.login()
        status, _, created = self.json_request(
            "POST", "/api/groups", {"name": "Тест-группа", "color": "#3fb950", "note": "api"}
        )
        self.assertEqual(status, 201, created)
        group_id = created["id"]
        self.assertEqual(created["name"], "Тест-группа")

        status, _, listing = self.json_request("GET", "/api/groups")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["id"] == group_id for item in listing["items"]))

        status, _, updated = self.json_request(
            "PATCH", f"/api/groups/{group_id}", {"note": "обновлено"}
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["note"], "обновлено")

        status, _, _ = self.json_request("DELETE", f"/api/groups/{group_id}")
        self.assertEqual(status, 200)
        status, _, _ = self.json_request("DELETE", f"/api/groups/{group_id}")
        self.assertEqual(status, 404)

    def test_group_assignment_to_user(self):
        self.login()
        status, _, group = self.json_request("POST", "/api/groups", {"name": "Клиенты API"})
        self.assertEqual(status, 201, group)
        status, _, user = self.json_request(
            "POST", "/api/users", {"username": "grouped", "days": 5, "limit_gb": 1}
        )
        self.assertEqual(status, 201, user)
        status, _, updated = self.json_request(
            "PATCH", f"/api/users/{user['id']}", {"group_id": group["id"]}
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["group_id"], group["id"])
        self.assertEqual(updated["group_name"], "Клиенты API")

        status, _, listing = self.json_request("GET", f"/api/users?group_id={group['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(all(item["group_id"] == group["id"] for item in listing["items"]))
        self.json_request("DELETE", f"/api/users/{user['id']}")
        self.json_request("DELETE", f"/api/groups/{group['id']}")

    def test_outbounds_crud_and_config(self):
        self.login()
        status, _, created = self.json_request(
            "POST",
            "/api/outbounds",
            {"name": "API SOCKS", "type": "socks", "address": "10.1.1.1", "port": 1080,
             "username": "u", "password": "p"},
        )
        self.assertEqual(status, 201, created)
        outbound_id = created["id"]
        self.assertEqual(created["tag"], "api-socks")

        nodes = self.json_request("GET", "/api/nodes")[2]["items"]
        node_id = nodes[0]["id"]
        status, _, config = self.json_request("GET", f"/api/nodes/{node_id}/config")
        self.assertEqual(status, 200)
        tags = [item["tag"] for item in config["outbounds"]]
        self.assertIn("api-socks", tags)

        status, _, updated = self.json_request(
            "PATCH", f"/api/outbounds/{outbound_id}", {"enabled": False}
        )
        self.assertEqual(status, 200, updated)
        self.assertFalse(updated["enabled"])
        status, _, config = self.json_request("GET", f"/api/nodes/{node_id}/config")
        tags = [item["tag"] for item in config["outbounds"]]
        self.assertNotIn("api-socks", tags)

        status, _, _ = self.json_request("DELETE", f"/api/outbounds/{outbound_id}")
        self.assertEqual(status, 200)

    def test_hosts_and_docs_endpoints(self):
        self.login()
        status, _, hosts = self.json_request("GET", "/api/hosts")
        self.assertEqual(status, 200, hosts)
        self.assertTrue(hosts["items"], "у демо-нод должны быть домены-маски")
        self.assertIn("nodes_count", hosts["items"][0])

        status, _, docs = self.json_request("GET", "/api/docs")
        self.assertEqual(status, 200, docs)
        paths = {(item["method"], item["path"]) for item in docs["items"]}
        self.assertIn(("GET", "/api/groups"), paths)
        self.assertIn(("POST", "/api/reality/scan"), paths)
        self.assertIn(("GET", "/api/agent/config"), paths)
        self.assertIn(("GET", "/api/node/agent.py"), paths)
        install_paths = [path for method, path in paths if path.startswith("/api/node/install/")]
        self.assertTrue(install_paths, "в документации есть ссылка установки")
        self.assertTrue(install_paths[0].endswith(".sh"))

    def test_reality_scan_api(self):
        self.login()
        status, _, job = self.json_request(
            "POST", "/api/reality/scan", {"targets": "127.0.0.1:9", "timeout": 1}
        )
        self.assertEqual(status, 201, job)
        self.assertIn("job_id", job)
        status, _, state = self.json_request("GET", f"/api/reality/scan/{job['job_id']}")
        self.assertEqual(status, 200, state)
        self.assertGreaterEqual(state["total"], 1)
        status, _, missing = self.json_request("GET", "/api/reality/scan/deadbeef")
        self.assertEqual(status, 404)

    def test_reality_apply_updates_node(self):
        self.login()
        nodes = self.json_request("GET", "/api/nodes")[2]["items"]
        node_id = nodes[0]["id"]
        status, _, updated = self.json_request(
            "POST", "/api/reality/apply", {"node_id": node_id, "host": "www.example.org", "port": 443}
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["sni"], "www.example.org")
        self.assertEqual(updated["dest"], "www.example.org:443")
        status, _, bad = self.json_request(
            "POST", "/api/reality/apply", {"node_id": node_id, "host": "не домен "}
        )
        self.assertEqual(status, 400)

    def test_updates_check_with_mock(self):
        self.login()
        from app import updates

        original = updates._fetch_latest

        def fake_fetch():
            return {
                "latest": "9.9.9",
                "notes": "Что нового",
                "url": "https://example.com/release",
                "published_at": "2026-01-01T00:00:00Z",
                "source": "release",
            }

        updates._fetch_latest = fake_fetch
        try:
            status, _, data = self.json_request("POST", "/api/updates/check")
        finally:
            updates._fetch_latest = original
        self.assertEqual(status, 200, data)
        self.assertEqual(data["latest"], "9.9.9")
        self.assertTrue(data["update_available"])
        self.assertIn("capability", data)

        status, _, info = self.json_request("GET", "/api/updates")
        self.assertEqual(status, 200)
        self.assertEqual(info["current"], config.APP_VERSION)

    def test_updates_apply_rejected_without_capability(self):
        self.login()
        from app import updates

        original = updates.capability
        updates.capability = lambda: {
            "mode": "manual", "label": "Вручную", "command": "", "hint": "",
            "instructions": "cd /opt/dfxray && sudo ./install.sh --yes",
        }
        try:
            status, _, data = self.json_request("POST", "/api/updates/apply")
        finally:
            updates.capability = original
        self.assertEqual(status, 400, data)
        self.assertIn("install.sh", data.get("error", ""))

    # --- мультисервер ---

    def test_node_connect_and_install_script(self):
        self.login()
        nodes = self.json_request("GET", "/api/nodes")[2]["items"]
        node_id = nodes[0]["id"]
        status, _, data = self.json_request("GET", f"/api/nodes/{node_id}/connect")
        self.assertEqual(status, 200, data)
        self.assertIn("/api/node/install/", data["one_liner"])
        self.assertIn("sudo bash", data["one_liner"])
        self.assertTrue(data["install_token"])
        self.assertIn("docker run", data["docker"])

        # скрипт доступен без авторизации по токену установки
        status, headers, body = self.request("GET", f"/api/node/install/{data['install_token']}.sh")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("dfxray-node.service", text)
        self.assertIn(data["node_token"], text)
        self.assertIn("DFX_PANEL_URL", text)
        self.assertIn("set -euo pipefail", text)

        # перевыпуск ссылки: старая перестаёт работать
        status, _, fresh = self.json_request(
            "POST", f"/api/nodes/{node_id}/install-token"
        )
        self.assertEqual(status, 200, fresh)
        self.assertNotEqual(fresh["install_token"], data["install_token"])
        status, _, _ = self.request("GET", f"/api/node/install/{data['install_token']}.sh")
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", f"/api/node/install/{fresh['install_token']}.sh")
        self.assertEqual(status, 200)

    def test_agent_source_is_public(self):
        status, headers, body = self.request("GET", "/api/node/agent.py")
        self.assertEqual(status, 200)
        self.assertIn("DF_Xray Node Agent", body.decode("utf-8"))

    def test_agent_heartbeat_metrics(self):
        self.login()
        nodes = self.json_request("GET", "/api/nodes")[2]["items"]
        node_id = nodes[0]["id"]
        node = self.json_request("GET", f"/api/nodes/{node_id}")[2]
        status, _, _ = self.json_request(
            "POST",
            "/api/agent/heartbeat",
            {
                "token": node["agent_token"],
                "xray_version": "Xray 25.9.11",
                "agent_version": "1.1.0",
                "xray_running": True,
                "uptime": 7200,
                "load1": 0.42,
                "memory": {"used": 512 * 1024 * 1024, "total": 2 * 1024 * 1024 * 1024},
                "revision": "rev-abc",
                "last_error": "",
            },
            headers={"X-Node-Token": node["agent_token"]},
        )
        self.assertEqual(status, 200)
        fresh = self.json_request("GET", f"/api/nodes/{node_id}")[2]
        self.assertEqual(fresh["status"], "online")
        self.assertEqual(fresh["health"], "ok")
        self.assertEqual(fresh["agent_version"], "1.1.0")
        self.assertTrue(fresh["xray_running"])
        self.assertEqual(fresh["uptime_seconds"], 7200)
        self.assertAlmostEqual(fresh["load1"], 0.42)
        self.assertEqual(fresh["mem_used"], 512 * 1024 * 1024)
        self.assertEqual(fresh["cfg_revision"], "rev-abc")

        status, _, _ = self.json_request(
            "POST",
            "/api/agent/heartbeat",
            {"token": node["agent_token"], "xray_running": False,
             "last_error": "xray -test: failed"},
            headers={"X-Node-Token": node["agent_token"]},
        )
        self.assertEqual(status, 200)
        fresh = self.json_request("GET", f"/api/nodes/{node_id}")[2]
        self.assertEqual(fresh["health"], "degraded")
        self.assertIn("failed", fresh["last_error"])

        # возвращаем ноду в норму, чтобы не влиять на другие тесты
        self.json_request(
            "POST",
            "/api/agent/heartbeat",
            {"token": node["agent_token"], "xray_running": True, "last_error": ""},
            headers={"X-Node-Token": node["agent_token"]},
        )

    def test_node_metrics_and_dashboard_traffic(self):
        self.login()
        nodes = self.json_request("GET", "/api/nodes")[2]["items"]
        node_id = nodes[0]["id"]
        node = self.json_request("GET", f"/api/nodes/{node_id}")[2]
        self.json_request(
            "POST",
            "/api/agent/report",
            {
                "token": node["agent_token"],
                "stats": {"users": {}, "node": {"up": 4096, "down": 8192}},
                "xray_running": True,
                "load1": 0.2,
            },
            headers={"X-Node-Token": node["agent_token"]},
        )
        _, _, dashboard = self.json_request("GET", "/api/dashboard")
        entry = next(item for item in dashboard["nodes"]["traffic"] if item["id"] == node_id)
        self.assertGreaterEqual(entry["total"], 12288)
        self.assertIn("health", entry)

        _, _, listing = self.json_request("GET", "/api/nodes")
        self.assertIn("offline", listing["summary"])
        self.assertIn("degraded", listing["summary"])
        self.assertIn("region", listing["items"][0])

    def test_node_crud_with_region(self):
        self.login()
        status, _, created = self.json_request(
            "POST", "/api/nodes",
            {"name": "Тестовый сервер", "address": "test.example.com", "region": "Финляндия",
             "port": 8443, "security": "none", "protocol": "vless", "transport": "tcp"},
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["region"], "Финляндия")
        status, _, updated = self.json_request(
            "PATCH", f"/api/nodes/{created['id']}", {"region": "Швеция", "enabled": False}
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["region"], "Швеция")
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["health"], "disabled")
        self.json_request("DELETE", f"/api/nodes/{created['id']}")

    # --- автонастройка ноды и каталог SNI ---

    def test_node_presets_and_sni_catalog(self):
        self.login()
        status, _, meta = self.json_request("GET", "/api/nodes/meta")
        self.assertEqual(status, 200, meta)
        ids = [item["id"] for item in meta["presets"]]
        self.assertIn("reality-vision", ids)
        self.assertIn("tls-ws", ids)
        self.assertGreaterEqual(len(meta["sni"]), 8)
        self.assertTrue(meta["default_sni"])

        # Создание ноды только по пресету: протокол, транспорт, SNI и dest
        # подставляет сама панель.
        status, _, created = self.json_request(
            "POST",
            "/api/nodes",
            {"name": "Пресет-нода", "address": "preset.example.com", "preset": "tls-ws"},
        )
        self.assertEqual(status, 201, created)
        self.assertEqual(created["protocol"], "vless")
        self.assertEqual(created["transport"], "ws")
        self.assertEqual(created["security"], "tls")
        self.assertEqual(created["port"], 8443)
        self.assertEqual(created["path"], "/dfws")
        self.assertEqual(created["sni"], "preset.example.com")

        # Несовместимые комбинации отклоняются с понятным текстом.
        status, _, broken = self.json_request(
            "POST",
            "/api/nodes",
            {"name": "Плохая", "address": "bad.example.com", "preset": "reality-vision",
             "transport": "ws"},
        )
        self.assertEqual(status, 400, broken)
        self.assertIn("Reality", broken["error"])

        status, _, flow = self.json_request(
            "POST",
            "/api/nodes",
            {"name": "Плохой flow", "address": "flow.example.com", "protocol": "vmess",
             "transport": "tcp", "security": "tls", "flow": "xtls-rprx-vision"},
        )
        self.assertEqual(status, 400, flow)

        status, _, bad_preset = self.json_request(
            "POST", "/api/nodes", {"name": "x", "address": "x.example.com", "preset": "nope"}
        )
        self.assertEqual(status, 400, bad_preset)

        self.json_request("DELETE", f"/api/nodes/{created['id']}")

    def test_sni_catalog_add_and_remove(self):
        self.login()
        status, _, listing = self.json_request("GET", "/api/sni")
        self.assertEqual(status, 200, listing)
        builtin = {item["domain"] for item in listing["items"] if item["source"] == "builtin"}
        self.assertIn("www.microsoft.com", builtin)

        status, _, added = self.json_request("POST", "/api/sni", {"domain": "cdn.example.com"})
        self.assertEqual(status, 201, added)
        self.assertTrue(added["added"])
        self.assertIn("cdn.example.com", [item["domain"] for item in added["items"]])

        status, _, again = self.json_request("POST", "/api/sni", {"domain": "https://cdn.example.com/"})
        self.assertEqual(status, 201, again)
        self.assertFalse(again["added"])
        self.assertEqual(
            [item["domain"] for item in again["items"]].count("cdn.example.com"), 1
        )

        status, _, bad = self.json_request("POST", "/api/sni", {"domain": "10.0.0.1"})
        self.assertEqual(status, 400, bad)

        status, _, removed = self.json_request("DELETE", "/api/sni/cdn.example.com")
        self.assertEqual(status, 200, removed)
        self.assertNotIn("cdn.example.com", [item["domain"] for item in removed["items"]])

        status, _, missing = self.json_request("DELETE", "/api/sni/cdn.example.com")
        self.assertEqual(status, 404, missing)

    # --- 2FA, API-токены, уведомления, drain и миграция ---

    def test_totp_login_flow(self):
        self.login()
        try:
            status, _, before = self.json_request("GET", "/api/account/2fa")
            self.assertEqual(status, 200)
            self.assertFalse(before["enabled"])

            status, _, start = self.json_request("POST", "/api/account/2fa/start")
            self.assertEqual(status, 200, start)
            self.assertTrue(start["secret"])
            self.assertIn("otpauth://", start["uri"])
            self.assertIn("<svg", start["qr_svg"])
            recovery = start["recovery_codes"]
            self.assertEqual(len(recovery), 8)

            status, _, bad = self.json_request(
                "POST", "/api/account/2fa/enable", {"code": "000000"}
            )
            self.assertEqual(status, 400, bad)

            status, _, enabled = self.json_request(
                "POST", "/api/account/2fa/enable", {"code": totp.code(start["secret"])}
            )
            self.assertEqual(status, 200, enabled)
            self.assertTrue(enabled["enabled"])

            # Вход без кода: пароль принят, но нужен второй фактор.
            other = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(other))
            status, _, step = self.json_request(
                "POST",
                "/api/auth/login",
                {"username": "admin", "password": "sup3r-secret-pass"},
                opener=opener,
            )
            self.assertEqual(status, 200, step)
            self.assertTrue(step["totp_required"])
            self.assertFalse(any(cookie.name == "dfx_session" for cookie in other))

            status, _, wrong = self.json_request(
                "POST",
                "/api/auth/login",
                {"username": "admin", "challenge": step["challenge"], "code": "000000"},
                opener=opener,
            )
            self.assertEqual(status, 401, wrong)

            # Резервный код одноразовый.
            status, _, ok = self.json_request(
                "POST",
                "/api/auth/login",
                {"username": "admin", "challenge": step["challenge"], "code": recovery[0]},
                opener=opener,
            )
            self.assertEqual(status, 200, ok)
            self.assertTrue(any(cookie.name == "dfx_session" for cookie in other))

            status, _, again = self.json_request(
                "POST",
                "/api/auth/login",
                {"username": "admin", "challenge": step["challenge"], "code": recovery[0]},
                opener=opener,
            )
            self.assertEqual(status, 401, again)

            status, _, disabled = self.json_request(
                "POST", "/api/account/2fa/disable", {"password": "sup3r-secret-pass"}, opener=opener
            )
            self.assertEqual(status, 200, disabled)
            self.assertFalse(disabled["enabled"])
            # После выключения 2FA вход снова ограничивается паролем.
            status, _, relogin = self.json_request(
                "POST",
                "/api/auth/login",
                {"username": "admin", "password": "sup3r-secret-pass"},
                opener=opener,
            )
            self.assertEqual(status, 200, relogin)
            self.assertFalse(relogin.get("totp_required", False))
        finally:
            db.run(
                "UPDATE admins SET totp_enabled = 0, totp_secret = NULL, totp_recovery = NULL "
                "WHERE username = 'admin'"
            )
            db.run("DELETE FROM sessions")
            db.run("DELETE FROM login_challenges")

    def test_api_tokens_scope(self):
        self.login()
        status, _, created = self.json_request(
            "POST", "/api/tokens", {"name": "monitor", "scope": "read"}
        )
        self.assertEqual(status, 201, created)
        self.assertTrue(created["token"].startswith("dfx_"))

        bare = urllib.request.build_opener()
        status, _, users = self.json_request(
            "GET", "/api/users", headers={"Authorization": f"Bearer {created['token']}"}, opener=bare
        )
        self.assertEqual(status, 200, users)

        status, _, denied = self.json_request(
            "POST",
            "/api/users",
            {"username": "token-user"},
            headers={"Authorization": f"Bearer {created['token']}"},
            opener=bare,
        )
        self.assertEqual(status, 403, denied)

        status, _, listing = self.json_request("GET", "/api/tokens")
        self.assertTrue(any(item["id"] == created["id"] for item in listing["items"]))

        status, _, removed = self.json_request("DELETE", f"/api/tokens/{created['id']}")
        self.assertEqual(status, 200, removed)
        status, _, revoked = self.json_request(
            "GET", "/api/users", headers={"Authorization": f"Bearer {created['token']}"}, opener=bare
        )
        self.assertEqual(status, 401, revoked)

        status, _, bad = self.json_request(
            "POST", "/api/tokens", {"name": "x", "scope": "root"}
        )
        self.assertEqual(status, 400, bad)

    def test_notifications_settings(self):
        self.login()
        status, _, data = self.json_request("GET", "/api/notifications")
        self.assertEqual(status, 200)
        self.assertIn("node_offline", data["available_events"])

        status, _, saved = self.json_request(
            "PATCH",
            "/api/notifications",
            {"enabled": True, "telegram_chat": "42", "events": ["node_offline", "node_recovered"]},
        )
        self.assertEqual(status, 200, saved)
        self.assertTrue(saved["enabled"])
        self.assertEqual(sorted(saved["events"]), ["node_offline", "node_recovered"])

        status, _, bad = self.json_request(
            "PATCH", "/api/notifications", {"events": ["nope"]}
        )
        self.assertEqual(status, 400, bad)

        status, _, check = self.json_request("POST", "/api/notifications/check")
        self.assertEqual(status, 200, check)
        self.assertIn("total", check)

        self.json_request("PATCH", "/api/notifications", {"enabled": False, "events": []})

    def test_node_drain_hides_links(self):
        self.login()
        status, _, user = self.json_request(
            "POST", "/api/users", {"username": "drain-check", "node_ids": "1", "days": 30}
        )
        self.assertEqual(status, 201, user)
        status, _, plain = self.request("GET", f"/sub/{user['sub_token']}")
        self.assertEqual(status, 200)
        self.assertIn(base64.b64decode(plain).decode("utf-8").count("vless"), [1])

        status, _, drained = self.json_request("POST", "/api/nodes/1/drain", {"drain": True})
        self.assertEqual(status, 200, drained.get("id"))
        status, _, empty = self.request("GET", f"/sub/{user['sub_token']}")
        self.assertEqual(status, 200)
        self.assertEqual(base64.b64decode(empty).decode("utf-8").strip(), "")

        status, _, back = self.json_request("POST", "/api/nodes/1/drain", {"drain": False})
        self.assertEqual(status, 200)
        status, _, restored = self.request("GET", f"/sub/{user['sub_token']}")
        self.assertGreaterEqual(base64.b64decode(restored).decode("utf-8").count("vless"), 1)
        self.json_request("DELETE", f"/api/users/{user['id']}")

    def test_node_migrate_moves_clients(self):
        self.login()
        status, _, user = self.json_request(
            "POST", "/api/users", {"username": "migrate-check", "node_ids": "1", "days": 30}
        )
        self.assertEqual(status, 201, user)
        status, _, result = self.json_request(
            "POST", "/api/nodes/1/migrate", {"to_node_id": 2}
        )
        self.assertEqual(status, 200, result)
        self.assertGreaterEqual(result["moved"], 1)

        status, _, fresh = self.json_request("GET", f"/api/users/{user['id']}")
        self.assertEqual(fresh["node_ids"], [2])

        status, _, same = self.json_request("POST", "/api/nodes/1/migrate", {"to_node_id": 1})
        self.assertEqual(status, 400, same)
        self.json_request("DELETE", f"/api/users/{user['id']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
