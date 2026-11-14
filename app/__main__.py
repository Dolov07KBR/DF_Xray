"""Точка входа: python -m app [serve|seed|reset-password|gen-config]."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import auth, config, db, repo, server, xray


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
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("serve", "seed", "reset-password", "gen-config", "check"):
        argv.insert(0, "serve")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
