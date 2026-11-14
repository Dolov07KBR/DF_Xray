"""Интеграционные тесты панели: живой HTTP-сервер + временная SQLite."""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

TMP_DIR = tempfile.mkdtemp(prefix="dfxray-tests-")
os.environ["DFX_DATA_DIR"] = TMP_DIR
os.environ["DFX_ADMIN_USERNAME"] = "admin"
os.environ["DFX_ADMIN_PASSWORD"] = "sup3r-secret-pass"
os.environ["DFX_SEED_DEMO"] = "0"

from app import config, db, seed
from app.server import Handler, PanelHTTPServer


class PanelTestCase(unittest.TestCase):
    server: PanelHTTPServer
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        config.ensure_dirs()
        db.init()
        seed.run(demo=True)
        cls.server = PanelHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    def setUp(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    # --- helpers ---

    def request(self, method: str, path: str, payload=None, headers=None, opener=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None
        request_headers = {"X-Requested-With": "DF_Xray"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with (opener or self.opener).open(request, timeout=15) as response:
                body = response.read()
                return response.status, dict(response.headers), body
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def json_request(self, method: str, path: str, payload=None, headers=None, opener=None):
        status, response_headers, body = self.request(method, path, payload, headers, opener)
        data = json.loads(body.decode("utf-8")) if body else None
        return status, response_headers, data

    def login(self, username="admin", password="sup3r-secret-pass"):
        status, headers, data = self.json_request(
            "POST", "/api/auth/login", {"username": username, "password": password}
        )
        self.assertEqual(status, 200, data)
        return data

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
        tags = [inbound["tag"] for inbound in config_data["inbounds"]]
        self.assertIn("api", tags)
        node_inbound = config_data["inbounds"][1]
        self.assertEqual(node_inbound["protocol"], "vless")
        self.assertEqual(node_inbound["streamSettings"]["security"], "reality")
        self.assertIn("privateKey", node_inbound["streamSettings"]["realitySettings"])
        self.assertTrue(node_inbound["settings"]["clients"])
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
            for client in config_response["config"]["inbounds"][1]["settings"]["clients"]
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
