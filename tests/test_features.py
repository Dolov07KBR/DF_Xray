"""Тесты новых возможностей 1.5: команды нодам, метрики, Telegram-бот."""

from __future__ import annotations

import json
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



class TelegramStub:
    """Подменяет вызовы Telegram API: тесты не должны ходить в сеть."""

    def __init__(self):
        self.calls = []
        self.original = None

    def install(self):
        self.original = tgbot._call

        def _call(method, payload=None, token="", timeout=30):
            self.calls.append((method, payload or {}))
            return {}

        tgbot._call = _call

    def restore(self):
        if self.original is not None:
            tgbot._call = self.original

    def text(self):
        return " ".join(str(call[1].get("text") or "") for call in self.calls)


class BotTests(_PanelBase):
    def setUp(self):
        super().setUp()
        self.telegram = TelegramStub()
        self.telegram.install()

    def tearDown(self):
        self.telegram.restore()
        super().tearDown()

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

    def test_start_shows_menu(self):
        tgbot.handle_update(
            {"message": {"chat": {"id": 900100}, "from": {"id": 900100, "username": "buyer"},
                         "text": "/start"}}
        )
        send = [call for call in self.telegram.calls if call[0] == "sendMessage"]
        self.assertTrue(send)
        self.assertIn("inline_keyboard", json.dumps(send[0][1], ensure_ascii=False))

    def test_trial_callback_creates_subscription(self):
        tgbot.save_settings({"trial_enabled": True, "trial_days": 2, "trial_gb": 5})
        update = {"callback_query": {
            "id": "cb1", "data": "trial", "from": {"id": 900200, "username": "trialer"},
            "message": {"chat": {"id": 900200}, "message_id": 11},
        }}
        tgbot.handle_update(update)
        text = self.telegram.text()
        self.assertIn("Пробный", text)
        self.assertIn("/sub/", text)
        user = db.one("SELECT * FROM users WHERE username = ?", ("tg_trialer",))
        self.assertIsNotNone(user)
        # повторный триал не создаёт второго клиента
        self.telegram.calls.clear()
        tgbot.handle_update(update)
        self.assertIn("уже использован", self.telegram.text())

    def test_stars_payment_grants_access(self):
        tgbot.save_settings({"payment_mode": "stars", "plans": [
            {"id": "s1", "title": "30 дней", "days": 30, "gb": 100, "price": 0, "stars": 150}
        ]})
        order_id = tgbot.create_order(
            900300, {"id": "s1", "title": "30 дней", "days": 30, "gb": 100, "price": 0, "stars": 150},
            username="stars_user",
        )
        tgbot.handle_pre_checkout({"id": "pc1", "invoice_payload": f"order:{order_id}"})
        self.assertEqual(self.telegram.calls[-1][0], "answerPreCheckoutQuery")
        self.assertTrue(self.telegram.calls[-1][1]["ok"])

        tgbot.handle_payment({"chat": {"id": 900300},
                              "successful_payment": {"invoice_payload": f"order:{order_id}",
                                                     "total_amount": 150}})
        saved = tgbot.order(order_id)
        self.assertEqual(saved["status"], "paid")
        self.assertTrue(saved["user_id"])
        self.assertEqual(saved["currency"], "XTR")
        self.assertIn("/sub/", self.telegram.text())

    def test_manual_order_pending_until_approve(self):
        tgbot.save_settings({"payment_mode": "manual", "plans": [
            {"id": "m9", "title": "Ручной", "days": 10, "gb": 20, "price": 300, "stars": 0}
        ]})
        tgbot.handle_update({"callback_query": {
            "id": "cb2", "data": "plan:m9", "from": {"id": 900400, "username": "manual_user"},
            "message": {"chat": {"id": 900400}, "message_id": 12},
        }})
        pending = [row for row in tgbot.list_orders() if row["tg_id"] == 900400]
        self.assertTrue(pending)
        order_id = pending[0]["id"]
        self.assertEqual(pending[0]["status"], "pending")
        self.assertIsNone(pending[0]["user_id"])

        paid = tgbot.mark_paid(order_id, note="перевод")
        self.assertIsNotNone(paid)
        self.assertTrue(paid["user_id"])
        self.assertTrue(paid["access"]["sub_url"])
        self.assertEqual(tgbot.order(order_id)["status"], "paid")
        self.assertEqual(tgbot.order(order_id)["note"], "перевод")


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


if __name__ == "__main__":
    unittest.main()
