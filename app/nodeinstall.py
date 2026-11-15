"""Установка ноды на новый сервер: скрипт и готовые команды.

Панель отдаёт по ссылке `/api/node/install/<install_token>.sh` bash-скрипт,
который ставит Xray и агент как systemd-сервис. Токен установки хранится
отдельно от токена агента: его можно перевыпустить, не ломая уже
подключённый сервер.
"""

from __future__ import annotations

import shlex
from typing import Any


def _q(value: str) -> str:
    return shlex.quote(value or "")


def panel_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def docker_command(url: str, node_token: str, port: int = 443, name: str = "dfxray-node") -> str:
    """Альтернатива systemd: контейнер с Xray и агентом."""
    return "\n".join(
        [
            f"docker run -d --name {_q(name)} --restart unless-stopped \\",
            f"  -e DFX_PANEL_URL={_q(url)} \\",
            f"  -e DFX_NODE_TOKEN={_q(node_token)} \\",
            "  -e DFX_POLL=30 \\",
            f"  -p {int(port)}:{int(port)} \\",
            "  -v dfxray-node:/etc/xray \\",
            "  ghcr.io/dfxray/node:latest",
        ]
    )


def compose_command(url: str, node_token: str, port: int = 443, name: str = "dfxray-node") -> str:
    body = f"""  {name}:
    image: ghcr.io/dfxray/node:latest
    container_name: {name}
    restart: unless-stopped
    environment:
      DFX_PANEL_URL: "{url}"
      DFX_NODE_TOKEN: "{node_token}"
      DFX_POLL: "30"
    ports:
      - "{int(port)}:{int(port)}"
    volumes:
      - dfxray-node:/etc/xray

volumes:
  dfxray-node:
"""
    return body


def install_script(
    *,
    url: str,
    node_token: str,
    node_name: str = "",
    port: int = 443,
    agent_url: str = "",
) -> str:
    """Bash-скрипт установки ноды (Xray + агент + systemd)."""
    url = panel_url(url)
    agent_url = agent_url or f"{url}/api/node/agent.py"
    title = node_name or "DF_Xray node"
    return f"""#!/usr/bin/env bash
# DF_Xray Panel → установка ноды «{title}».
# Скрипт идемпотентен: повторный запуск обновляет агент и перезапускает сервис.
set -euo pipefail

PANEL_URL={_q(url)}
NODE_TOKEN={_q(node_token)}
AGENT_URL={_q(agent_url)}
XRAY_PORT={int(port)}

log() {{ printf '\\033[1;35m[dfxray]\\033[0m %s\\n' "$*"; }}
die() {{ printf '\\033[1;31m[dfxray] %s\\033[0m\\n' "$*" >&2; exit 1; }}

[ "$(id -u)" = "0" ] || die "запустите от root: curl -fsSL {url}/api/node/install/… | sudo bash"

command -v curl >/dev/null || {{
  if command -v apt-get >/dev/null; then apt-get update -qq && apt-get install -y -qq curl ca-certificates;
  elif command -v dnf >/dev/null; then dnf install -y -q curl ca-certificates;
  elif command -v yum >/dev/null; then yum install -y -q curl ca-certificates;
  elif command -v apk >/dev/null; then apk add --no-cache curl ca-certificates;
  else die "не найден curl и пакетный менеджер"; fi
}}
command -v python3 >/dev/null || {{
  if command -v apt-get >/dev/null; then apt-get install -y -qq python3;
  elif command -v dnf >/dev/null; then dnf install -y -q python3;
  elif command -v yum >/dev/null; then yum install -y -q python3;
  elif command -v apk >/dev/null; then apk add --no-cache python3;
  else die "не найден python3"; fi
}}

log "проверяю связь с панелью $PANEL_URL"
curl -fsS --max-time 20 "$PANEL_URL/healthz" >/dev/null \\
  || die "панель недоступна из этого сервера. Нужен публичный HTTPS-адрес панели (см. docs/MULTISERVER.md)"

if [ ! -x /usr/local/bin/xray ]; then
  log "устанавливаю Xray-core"
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install \\
    || die "не удалось установить Xray"
else
  log "Xray уже установлен: $(/usr/local/bin/xray -version 2>/dev/null | head -1)"
fi

log "ставлю агент панели"
install -d -m 750 /opt/dfxray-agent
curl -fsSL --max-time 60 "$AGENT_URL" -o /opt/dfxray-agent/agent.py \\
  || die "не удалось скачать агент с панели"
chmod 750 /opt/dfxray-agent/agent.py

install -d -m 750 /etc/xray
if ! id xray >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin xray 2>/dev/null || true
fi
chown -R xray:xray /etc/xray 2>/dev/null || true

log "создаю systemd-сервис dfxray-node"
cat >/etc/systemd/system/dfxray-node.service <<UNIT
[Unit]
Description=DF_Xray node agent ({title})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=DFX_PANEL_URL=$PANEL_URL
Environment=DFX_NODE_TOKEN=$NODE_TOKEN
Environment=DFX_XRAY_BIN=/usr/local/bin/xray
Environment=DFX_CONFIG_PATH=/etc/xray/config.json
Environment=DFX_POLL=30
Environment=DFX_LOG_LEVEL=info
ExecStart=/usr/bin/python3 /opt/dfxray-agent/agent.py
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable dfxray-node >/dev/null 2>&1 || true
systemctl restart dfxray-node

log "жду первый конфиг от панели"
sleep 4
systemctl is-active --quiet dfxray-node \\
  || {{ journalctl -u dfxray-node -n 30 --no-pager || true; die "сервис не запустился"; }}

log "готово. Нода «{title}» подключена к $PANEL_URL"
log "статус: systemctl status dfxray-node · логи: journalctl -u dfxray-node -f"
log "порт $XRAY_PORT должен быть открыт в фаерволе провайдера"
"""


def connect_payload(node: dict[str, Any], base_url: str, install_token: str) -> dict[str, Any]:
    """Всё, что нужно интерфейсу, чтобы показать команду установки."""
    url = panel_url(base_url)
    token = node.get("agent_token") or ""
    port = int(node.get("port") or 443)
    slug = f"node-{node.get('id')}"
    return {
        "panel_url": url,
        "node_token": token,
        "install_token": install_token,
        "script_url": f"{url}/api/node/install/{install_token}.sh",
        "one_liner": f"curl -fsSL {url}/api/node/install/{install_token}.sh | sudo bash",
        "systemd": f"curl -fsSL {url}/api/node/install/{install_token}.sh | sudo bash",
        "docker": docker_command(url, token, port, slug),
        "compose": compose_command(url, token, port, slug),
        "agent_url": f"{url}/api/node/agent.py",
        "port": port,
        "https": url.startswith("https://"),
    }
