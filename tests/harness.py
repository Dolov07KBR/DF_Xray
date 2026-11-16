"""Общий стенд для интеграционных тестов: живой HTTP-сервер + временная SQLite."""

from __future__ import annotations

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
os.environ.setdefault("DFX_DATA_DIR", TMP_DIR)
os.environ.setdefault("DFX_ADMIN_USERNAME", "admin")
os.environ.setdefault("DFX_ADMIN_PASSWORD", "sup3r-secret-pass")
os.environ.setdefault("DFX_SEED_DEMO", "0")

from app import config, db, seed
from app.server import Handler, PanelHTTPServer


class PanelHarness(unittest.TestCase):
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

