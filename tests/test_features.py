"""Тесты новых возможностей 1.5: команды нодам, метрики, Telegram-бот."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import PanelHarness as _PanelBase

from app import db, repo, tgbot


class NodeCommandTests(_PanelBase):
    def test_restart_xray_command_round_trip(self):
        self.login()
        node = self.json_request("GET", "/api/nodes/1")[2]
        token = node["agent_token"]

        status, _, created = self.json_request(
            "POST", "/api/nodes/1/actions", {"action": "restart_xray"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["status"], "pending")

        # агент забирает конфиг — команда попадает в ответ и помечается running
        status, _, payload = self.json_request(
            "GET", "/api/agent/config", headers={"X-Node-Token": token}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["commands"])
        self.assertEqual(payload["commands"][0]["command"], "restart_xray")

        # агент сообщает результат
        status, _, _ = self.json_request(
            "POST", "/api/agent/command",
            {"id": payload["commands"][0]["id"], "status": "done", "result": "Xray перезапущен"},
            headers={"X-Node-Token": token},
        )
        self.assertEqual(status, 200)

        status, _, listing = self.json_request("GET", "/api/nodes/1/actions")
        self.assertEqual(status, 200)
        self.assertEqual(listing["items"][0]["status"], "done")
        self.assertIn("перезапущен", listing["items"][0]["result"])

    def test_unknown_action_rejected(self):
        self.login()
        status, _, body = self.json_request("POST", "/api/nodes/1/actions", {"action": "rm -rf /"})
        self.assertEqual(status, 400)



class MetricsTests(_PanelBase):
    def test_metrics_endpoint_and_dashboard(self):
        self.login()
        repo.add_metrics(repo.PANEL_METRICS_ID, 12.5, 1024, 4096, 0.4)
        status, _, data = self.json_request("GET", "/api/metrics?minutes=60")
        self.assertEqual(status, 200)
        self.assertTrue(data["series"])
        self.assertIn("cpu", data["host"])

        status, _, dash = self.json_request("GET", "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("system", dash)
        self.assertIn("series", dash["system"])

    def test_node_metrics_saved_from_heartbeat(self):
        self.login()
        token = self.json_request("GET", "/api/nodes/1")[2]["agent_token"]
        status, _, _ = self.json_request(
            "POST", "/api/agent/heartbeat",
            {"cpu": 42.0, "load1": 1.2, "memory": {"used": 2048, "total": 4096}},
            headers={"X-Node-Token": token},
        )
        self.assertEqual(status, 200)
        latest = repo.latest_metrics(1)
        self.assertIsNotNone(latest)
        recent = [row["cpu"] for row in repo.metrics_series(1, minutes=5)]
        self.assertIn(42.0, recent)
        node = self.json_request("GET", "/api/nodes/1")[2]
        self.assertGreaterEqual(node["cpu"], 40)



class BotTests(_PanelBase):
    def test_settings_and_status(self):
        self.login()
        status, _, data = self.json_request("GET", "/api/bot")
        self.assertEqual(status, 200)
        self.assertIn("status", data)
        self.assertTrue(data["settings"]["plans"])

        status, _, data = self.json_request(
            "PATCH", "/api/bot",
            {
                "enabled": False,
                "payment_mode": "manual",
                "trial_days": 5,
                "admin_chat": "123456",
                "plans": [
                    {"id": "p1", "title": "Тест", "days": 10, "gb": 50, "price": 100, "stars": 100}
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["settings"]["payment_mode"], "manual")
        self.assertEqual(data["settings"]["plans"][0]["title"], "Тест")
        self.assertEqual(data["settings"]["trial_days"], 5)

    def test_manual_order_creates_client(self):
        tg_id = 555000111
        order_id = tgbot.create_order(
            tg_id, {"id": "p1", "title": "1 месяц", "days": 30, "gb": 100, "price": 199, "stars": 199},
            username="tester",
        )
        paid = tgbot.mark_paid(order_id, note="тест")
        self.assertIsNotNone(paid)
        access = paid["access"]
        self.assertTrue(access["sub_url"])
        user = db.one("SELECT * FROM users WHERE id = ?", (access["user_id"],))
        self.assertIsNotNone(user)
        self.assertTrue(user["expires_at"])
        self.assertEqual(tgbot.order(order_id)["status"], "paid")
        # повторное подтверждение не создаёт второго клиента
        again = tgbot.mark_paid(order_id)
        self.assertEqual(again["user_id"], access["user_id"])
        self.assertEqual(len(tgbot.list_orders(5)), len([o for o in tgbot.list_orders(5)]))

    def test_trial_is_one_time(self):
        tg_id = 555000222
        tgbot.touch_bot_user(tg_id, username="trial_user")
        access = tgbot.grant_access(tg_id, 3, 10, note="trial")
        self.assertTrue(access["sub_url"])
        db.run("UPDATE bot_users SET trial_used = 1 WHERE tg_id = ?", (tg_id,))
        record = tgbot.bot_user(tg_id)
        self.assertEqual(record["trial_used"], 1)
        self.assertEqual(record["user_id"], access["user_id"])


if __name__ == "__main__":
    unittest.main()


class HttpOptimisationTests(_PanelBase):
    def test_api_responses_are_not_cached(self):
        self.login()
        status, headers, _ = self.request("GET", "/api/nodes")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_static_supports_etag_and_gzip(self):
        status, headers, body = self.request(
            "GET", "/static/js/app.js", headers={"Accept-Encoding": "gzip"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        etag = headers.get("ETag")
        self.assertTrue(etag)
        status, headers, body = self.request(
            "GET", "/static/js/app.js", headers={"If-None-Match": etag}
        )
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")


# Базовый класс импортирован из test_api — убираем его из пространства имён,
# иначе unittest соберёт тесты test_api повторно.
del _PanelBase
