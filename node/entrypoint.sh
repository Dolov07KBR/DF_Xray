#!/bin/sh
# Точка входа ноды: проверяет окружение и запускает агента.
set -eu

if [ -z "${DFX_PANEL_URL:-}" ]; then
  echo "[dfxray-node] ОШИБКА: не задан DFX_PANEL_URL (адрес панели)" >&2
  exit 2
fi
if [ -z "${DFX_NODE_TOKEN:-}" ]; then
  echo "[dfxray-node] ОШИБКА: не задан DFX_NODE_TOKEN (токен ноды из панели)" >&2
  exit 2
fi

mkdir -p "$(dirname "${DFX_CONFIG_PATH:-/etc/xray/config.json}")"
chown -R xray:xray "$(dirname "${DFX_CONFIG_PATH:-/etc/xray/config.json}")" 2>/dev/null || true

echo "[dfxray-node] старт агента · панель ${DFX_PANEL_URL} · xray ${DFX_XRAY_BIN}"
exec python3 /opt/dfxray/agent.py
