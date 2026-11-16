#!/usr/bin/env python3
"""Нагрузочный тест DF_Xray Panel.

Скрипт на стандартной библиотеке: поднимает пул потоков, долбит выбранные
эндпоинты и считает RPS, ошибки и перцентили задержки. Умеет три профиля:

  panel  — то, что делает браузер админа: дашборд, список клиентов, ноды;
  agent  — то, что делают агенты нод: конфиг + heartbeat + отчёт трафика;
  sub    — выдача подписок клиентам (/sub/<token>, plain и base64).

Примеры:

  # только панель, 30 воркеров, 30 секунд
  python3 tools/loadtest.py --base http://127.0.0.1:8000 \
      --user admin --password 'panel-demo-2026' --profile panel --workers 30 --duration 30

  # агенты трёх нод и клиентские подписки
  python3 tools/loadtest.py --base http://127.0.0.1:8000 \
      --user admin --password '...' --profile agent --workers 12 --duration 30
  python3 tools/loadtest.py --base http://127.0.0.1:8000 \
      --profile sub --sub-token <token> --workers 20 --duration 30

Только stdlib (Python 3.9+). Для честного замера запускайте панель на том же
VPS, где она и будет работать, и держите нагрузку вне этого VPS.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any


def request(
    base: str,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, bytes]:
    req = urllib.request.Request(
        base + path,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Session:
    """Логин админа: cookie-сессия или Bearer-токен."""

    def __init__(self, base: str, user: str, password: str, token: str) -> None:
        self.base = base
        self.headers: dict[str, str] = {
            "X-Requested-With": "DF_Xray",
            "Content-Type": "application/json",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
            self.login_cookie = ""
            return
        payload = json.dumps({"username": user, "password": password}).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/auth/login",
            data=payload,
            headers=self.headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.headers.get_all("Set-Cookie") or []
            data = json.loads(response.read() or b"{}")
        if data.get("totp_required"):
            raise SystemExit("включена 2FA: используйте API-токен (--token) вместо пароля")
        pairs = [item.split(";", 1)[0].strip() for item in raw]
        self.login_cookie = "; ".join(pair for pair in pairs if pair)
        if not self.login_cookie:
            raise SystemExit("сервер не выдал cookie сессии")
        self.headers["Cookie"] = self.login_cookie


def panel_scenario(session: Session) -> list[tuple[str, str, bytes | None, dict[str, str]]]:
    """Набор запросов, похожий на живую работу администратора."""
    return [
        ("GET", "/api/dashboard", None, session.headers),
        ("GET", "/api/users?limit=50", None, session.headers),
        ("GET", "/api/nodes", None, session.headers),
        ("GET", "/api/subscriptions", None, session.headers),
        ("GET", "/api/settings", None, session.headers),
        ("GET", "/api/audit?limit=30", None, session.headers),
    ]


def agent_scenario(tokens: list[str]) -> list[tuple[str, str, bytes | None, dict[str, str]]]:
    calls: list[tuple[str, str, bytes | None, dict[str, str]]] = []
    for index, token in enumerate(tokens):
        headers = {"X-Node-Token": token, "Content-Type": "application/json"}
        heartbeat = json.dumps(
            {
                "xray_running": True,
                "agent_version": "loadtest",
                "uptime_seconds": 1000 + index,
                "load1": 0.2 + index * 0.05,
                "mem_used": 200 * 1024 * 1024,
                "mem_total": 1024 * 1024 * 1024,
            }
        ).encode("utf-8")
        calls.append(("GET", "/api/agent/config", None, headers))
        calls.append(("POST", "/api/agent/heartbeat", heartbeat, headers))
    return calls


def sub_scenario(tokens: list[str]) -> list[tuple[str, str, bytes | None, dict[str, str]]]:
    calls: list[tuple[str, str, bytes | None, dict[str, str]]] = []
    for token in tokens:
        calls.append(("GET", f"/sub/{token}", None, {}))
        calls.append(("GET", f"/sub/{token}?format=base64", None, {}))
    return calls


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * len(ordered) + 0.5) - 1))
    return ordered[index]


def run(args: argparse.Namespace) -> dict[str, Any]:
    base = args.base.rstrip("/")
    if args.profile == "panel":
        calls = panel_scenario(Session(base, args.user, args.password, args.token))
    elif args.profile == "agent":
        calls = agent_scenario(args.node_tokens)
    else:
        calls = sub_scenario(args.sub_token)

    if not calls:
        raise SystemExit("нечего нагружать: нет токенов/нод для выбранного профиля")

    counters = {"ok": 0, "fail": 0}
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    lock = threading.Lock()
    stop_at = time.time() + args.duration
    started = time.time()

    def worker(seed: int) -> None:
        local_random = random.Random(seed)
        while time.time() < stop_at:
            method, path, body, headers = local_random.choice(calls)
            begin = time.perf_counter()
            try:
                status, _ = request(base, method, path, body, headers)
            except Exception:  # сетевые ошибки считаем провалом
                status = 0
            elapsed = (time.perf_counter() - begin) * 1000
            with lock:
                latencies.append(elapsed)
                statuses[status] = statuses.get(status, 0) + 1
                if 200 <= status < 400:
                    counters["ok"] += 1
                else:
                    counters["fail"] += 1

    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(args.workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    total_time = time.time() - started

    total = counters["ok"] + counters["fail"]
    return {
        "profile": args.profile,
        "workers": args.workers,
        "duration_s": round(total_time, 2),
        "requests": total,
        "ok": counters["ok"],
        "fail": counters["fail"],
        "error_rate": round(counters["fail"] / total * 100, 2) if total else 0.0,
        "rps": round(total / total_time, 1) if total_time else 0.0,
        "p50_ms": round(percentile(latencies, 0.50), 1),
        "p95_ms": round(percentile(latencies, 0.95), 1),
        "p99_ms": round(percentile(latencies, 0.99), 1),
        "mean_ms": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        "statuses": {str(key): value for key, value in sorted(statuses.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Нагрузочный тест DF_Xray Panel")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="адрес панели")
    parser.add_argument("--profile", choices=("panel", "agent", "sub"), default="panel")
    parser.add_argument("--user", default="admin", help="логин администратора")
    parser.add_argument("--password", default="", help="пароль администратора")
    parser.add_argument("--token", default="", help="API-токен вместо пароля")
    parser.add_argument("--sub-token", default="", help="токен подписки (профиль sub)")
    parser.add_argument("--node-tokens", default="", help="токены агентов через запятую")
    parser.add_argument("--node-ids", default="", help="id нод через запятую (для отчёта)")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="вывести результат как JSON")
    parser.add_argument("--markdown", action="store_true", help="вывести строку для docs/LOADTEST.md")
    args = parser.parse_args(argv)

    args.node_tokens = [item.strip() for item in args.node_tokens.split(",") if item.strip()]
    args.node_ids = [int(item) for item in args.node_ids.split(",") if item.strip().isdigit()]
    args.sub_token = [item.strip() for item in args.sub_token.split(",") if item.strip()]

    if args.profile == "sub" and not args.sub_token:
        raise SystemExit("для профиля sub нужен --sub-token")
    if args.profile == "agent" and not args.node_tokens:
        raise SystemExit("для профиля agent нужен --node-tokens")
    if args.profile == "panel" and not args.token and not args.password:
        raise SystemExit("нужен --password или --token")

    result = run(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(
            f"| {result['profile']} | {result['workers']} | {result['duration_s']} с | "
            f"{result['rps']} | {result['p50_ms']} | {result['p95_ms']} | {result['p99_ms']} | "
            f"{result['error_rate']} % |"
        )
    else:
        print(f"профиль: {result['profile']}, воркеров: {result['workers']}, "
              f"длительность: {result['duration_s']} с")
        print(f"запросов: {result['requests']} (ok {result['ok']}, ошибок {result['fail']})")
        print(f"RPS: {result['rps']}")
        print(f"задержка: p50 {result['p50_ms']} мс · p95 {result['p95_ms']} мс · "
              f"p99 {result['p99_ms']} мс · среднее {result['mean_ms']} мс")
        print(f"коды ответов: {result['statuses']}")
    return 0 if result["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
