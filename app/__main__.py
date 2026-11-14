"""Точка входа: python -m app [serve|seed|user-add|node-add|...]."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from . import auth, config, db, repo, server, xray

KNOWN_COMMANDS = (
    "serve",
    "seed",
    "reset-password",
    "gen-config",
    "check",
    "node-add",
    "node-token",
    "user-add",
    "backup",
)


def cmd_serve(args: argparse.Namespace) -> int:
    if args.port:
        config.PORT = args.port
    if args.host:
        config.HOST = args.host
    server.serve()
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from . import seed

    db.init()
    seed.run(demo=not args.empty, force=args.force)
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    db.init()
    username = args.username or config.BOOTSTRAP_USERNAME
    row = auth.find_admin(username)
    if row is None:
        print(f"Администратор {username!r} не найден.", file=sys.stderr)
        return 1
    password = args.password or getpass.getpass("Новый пароль: ")
    if len(password) < 8:
        print("Пароль должен быть не короче 8 символов.", file=sys.stderr)
        return 2
    auth.set_password(row["id"], password)
    print(f"Пароль администратора {username!r} обновлён, все сессии закрыты.")
    return 0


def cmd_gen_config(args: argparse.Namespace) -> int:
    db.init()
    row = repo.get_node(args.node_id)
    if row is None:
        print(f"Нода #{args.node_id} не найдена.", file=sys.stderr)
        return 1
    users = repo.node_traffic_users(row["id"])
    data = xray.build_config(row, users, db.get_settings())
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"Конфиг ноды #{row['id']} ({row['name']}) записан в {args.output}")
    else:
        print(text)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Проверка состояния панели без запуска сервера."""
    db.init()
    users, total = repo.list_users(limit=10000)
    nodes = repo.list_nodes()
    print(f"База: {config.DB_PATH}")
    print(f"Пользователей: {total} (активных: {sum(1 for u in users if u['status']=='active')})")
    print(f"Нод: {len(nodes)} (online: {sum(1 for n in nodes if n['status']=='online')})")
    print(f"Администраторы: {db.scalar('SELECT COUNT(*) FROM admins')}")
    return 0


def _public_base() -> str:
    return (db.get_setting("public_base_url") or config.BASE_URL or "").rstrip("/")


def cmd_node_add(args: argparse.Namespace) -> int:
    """Создать ноду из командной строки (используется установщиком)."""
    db.init()
    private_key = args.private_key or ""
    public_key = args.public_key or ""
    if args.security == "reality" and not args.skip_reality_keys and not private_key:
        try:
            private_key, public_key = xray.generate_reality_keypair()
        except RuntimeError as exc:
            print(f"Reality-ключи не сгенерированы: {exc}", file=sys.stderr)
    flow = args.flow
    if flow is None:
        flow = (
            "xtls-rprx-vision"
            if args.protocol == "vless" and args.transport == "tcp" and args.security != "none"
            else ""
        )
    payload = {
        "name": args.name,
        "address": args.address,
        "port": args.port,
        "protocol": args.protocol,
        "transport": args.transport,
        "security": args.security,
        "sni": args.sni,
        "dest": args.dest,
        "short_id": args.short_id,
        "path": args.path,
        "service_name": args.service_name,
        "flow": flow,
        "fingerprint": args.fingerprint,
        "private_key": private_key,
        "public_key": public_key,
        "note": args.note,
        "sort": args.sort,
    }
    try:
        node_id = repo.create_node(payload)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    row = repo.get_node(node_id)
    data = repo.serialize_node(row, with_secrets=True)
    if args.print_token:
        print(data["agent_token"])
        return 0
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return 0
    print(f"Нода #{data['id']} «{data['name']}» создана")
    print(f"  адрес:      {data['address']}:{data['port']}")
    print(f"  протокол:   {data['protocol']} / {data['transport']} / {data['security']}")
    if data["public_key"]:
        print(f"  public key: {data['public_key']}")
    print(f"  agent token: {data['agent_token']}")
    return 0


def cmd_node_token(args: argparse.Namespace) -> int:
    db.init()
    row = repo.get_node(args.node_id)
    if row is None:
        print(f"Нода #{args.node_id} не найдена.", file=sys.stderr)
        return 1
    print(row["agent_token"])
    return 0


def cmd_user_add(args: argparse.Namespace) -> int:
    db.init()
    payload = {
        "username": args.username,
        "email": args.email,
        "days": args.days,
        "limit_gb": args.limit_gb,
        "device_limit": args.devices,
        "note": args.note,
        "flow": args.flow,
    }
    try:
        user_id = repo.create_user(payload)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    row = repo.get_user(user_id)
    base = _public_base()
    data = repo.serialize_user(row, base)
    links = xray.build_links(row, repo.list_nodes(), db.get_settings().get("panel_title", "DF_Xray"))
    data["links"] = [item["link"] for item in links]
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
        return 0
    print(f"Пользователь «{data['username']}» создан (#{data['id']})")
    print(f"  UUID:      {data['uuid']}")
    print(f"  подписка:  {data['sub_url'] or '/sub/' + data['sub_token']}")
    print(f"  срок:      {data['expires_at'] or 'бессрочно'}")
    print(f"  лимит:     {'без лимита' if not data['limit_bytes'] else str(data['limit_gb']) + ' ГБ'}")
    print(f"  нод:       {len(links)}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """Консистентная копия SQLite через backup API."""
    import sqlite3

    db.init()
    target = args.output
    source = sqlite3.connect(config.DB_PATH, timeout=20)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()
    size = os.path.getsize(target)
    print(f"Бэкап базы сохранён: {target} ({size} байт)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dfxray", description=config.APP_NAME)
    parser.add_argument("--version", action="version", version=config.APP_VERSION)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="запустить панель (по умолчанию)")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)
    serve.set_defaults(func=cmd_serve)

    seed = sub.add_parser("seed", help="создать демо-данные")
    seed.add_argument("--force", action="store_true", help="добавить данные повторно")
    seed.add_argument("--empty", action="store_true", help="только схема, без демо")
    seed.set_defaults(func=cmd_seed)

    reset = sub.add_parser("reset-password", help="сменить пароль администратора")
    reset.add_argument("--username", default="")
    reset.add_argument("--password", default="")
    reset.set_defaults(func=cmd_reset_password)

    gen = sub.add_parser("gen-config", help="напечатать конфиг Xray для ноды")
    gen.add_argument("node_id", type=int)
    gen.add_argument("-o", "--output", default="")
    gen.set_defaults(func=cmd_gen_config)

    check = sub.add_parser("check", help="показать состояние базы")
    check.set_defaults(func=cmd_check)

    node_add = sub.add_parser("node-add", help="создать ноду из CLI")
    node_add.add_argument("--name", required=True)
    node_add.add_argument("--address", required=True)
    node_add.add_argument("--port", type=int, default=443)
    node_add.add_argument("--protocol", default="vless", choices=("vless", "vmess", "trojan"))
    node_add.add_argument("--transport", default="tcp", choices=repo.TRANSPORTS)
    node_add.add_argument("--security", default="reality", choices=repo.SECURITIES)
    node_add.add_argument("--sni", default="www.microsoft.com")
    node_add.add_argument("--dest", default="")
    node_add.add_argument("--short-id", default="")
    node_add.add_argument("--path", default="/")
    node_add.add_argument("--service-name", default="")
    node_add.add_argument("--fingerprint", default="chrome")
    node_add.add_argument("--flow", default=None, help="по умолчанию xtls-rprx-vision для VLESS+TCP+TLS/Reality")
    node_add.add_argument("--private-key", default="")
    node_add.add_argument("--public-key", default="")
    node_add.add_argument("--skip-reality-keys", action="store_true")
    node_add.add_argument("--note", default="")
    node_add.add_argument("--sort", type=int, default=0)
    node_add.add_argument("--json", action="store_true")
    node_add.add_argument("--print-token", action="store_true", help="напечатать только токен агента")
    node_add.set_defaults(func=cmd_node_add)

    node_token = sub.add_parser("node-token", help="напечатать токен ноды")
    node_token.add_argument("node_id", type=int)
    node_token.set_defaults(func=cmd_node_token)

    user_add = sub.add_parser("user-add", help="создать пользователя из CLI")
    user_add.add_argument("--username", required=True)
    user_add.add_argument("--email", default="")
    user_add.add_argument("--days", type=int, default=30, help="0 — бессрочно")
    user_add.add_argument("--limit-gb", type=float, default=0, help="0 — без лимита")
    user_add.add_argument("--devices", type=int, default=0)
    user_add.add_argument("--note", default="")
    user_add.add_argument("--flow", default="")
    user_add.add_argument("--json", action="store_true")
    user_add.set_defaults(func=cmd_user_add)

    backup = sub.add_parser("backup", help="сделать копию базы")
    backup.add_argument("-o", "--output", required=True)
    backup.set_defaults(func=cmd_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    elif argv[0] not in KNOWN_COMMANDS and argv[0] not in ("-h", "--help", "-V", "--version"):
        argv.insert(0, "serve")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
