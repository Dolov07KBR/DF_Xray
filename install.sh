#!/usr/bin/env bash
# ==========================================================================
#  DF_Xray Panel — установщик для VPS.
#
#  Быстрый старт одной командой:
#    curl -fsSL https://raw.githubusercontent.com/Dolov07KBR/DF_Xray/main/install.sh | sudo bash
#
#  С флагами (после `bash -s --`):
#    curl -fsSL .../install.sh | sudo bash -s -- --domain panel.example.com --with-node
#
#  Или из клонированного репозитория:
#    sudo ./install.sh --domain panel.example.com --with-node
# ==========================================================================
set -Eeuo pipefail

APP_NAME="DF_Xray Panel"
APP_VERSION="1.5.1"
REPO="${DFX_REPO:-Dolov07KBR/DF_Xray}"
DEFAULT_REF="${DFX_REF:-main}"
INSTALL_DIR="${DFX_INSTALL_DIR:-/opt/dfxray}"
BIN_DIR="${DFX_BIN_DIR:-/usr/local/bin}"
CONF_DIR="${DFX_CONF_DIR:-/etc/dfxray}"
XRAY_VERSION_DEFAULT="25.9.11"

DOMAIN="${DFX_DOMAIN:-}"
ACME_EMAIL="${DFX_EMAIL:-}"
PANEL_PORT="${DFX_PANEL_PORT:-8000}"
ADMIN_USER="${DFX_ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${DFX_ADMIN_PASSWORD:-}"
NODE_MODE="${DFX_NODE_MODE:-ask}"     # ask | yes | no
NODE_PORT="${DFX_NODE_PORT:-}"
NODE_NAME="${DFX_NODE_NAME:-}"
NODE_ADDRESS="${DFX_NODE_ADDRESS:-}"
REF="${DFX_REF:-$DEFAULT_REF}"
SEED_DEMO="${DFX_SEED_DEMO:-0}"
ASSUME_YES=0
DRY_RUN=0
UNINSTALL=0
SKIP_DOCKER_INSTALL=0
STARTED_AT="$(date +%s)"

COMPOSE=()
PANEL_URL=""
PANEL_BIND="0.0.0.0"
EXISTING_ENV=0
EXISTING_URL=""
PORT_FLAG=0

# ---------------------------------------------------------------- вывод ---
if [ -t 1 ] && [ "${NO_COLOR:-0}" != "1" ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
    C_CYAN=$'\033[36m'; C_VIOLET=$'\033[35m'
else
    C_RESET=""; C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_CYAN=""; C_VIOLET=""
fi

info() { printf '%s•%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%s✗%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
step() { printf '\n%s▸ %s%s\n' "$C_VIOLET$C_BOLD" "$*" "$C_RESET"; }

on_error() {
    local code=$?
    printf '\n%s✗ Установка прервана (код %s).%s\n' "$C_RED" "$code" "$C_RESET" >&2
    printf '  Логи: %s\n' "docker compose -f $INSTALL_DIR/docker-compose.yml logs --tail=100" >&2
    exit "$code"
}
trap on_error ERR

usage() {
    cat <<EOF
$APP_NAME $APP_VERSION — установка на VPS

Использование:
  sudo ./install.sh [флаги]
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sudo bash -s -- [флаги]

Флаги:
  -d, --domain <домен>     домен для автоматического HTTPS (Caddy + Let's Encrypt)
      --email <адрес>      e-mail для ACME (необязательно)
  -p, --port <порт>        порт панели без домена (по умолчанию 8000)
      --dir <путь>         каталог установки (по умолчанию /opt/dfxray)
      --ref <ref>          git-ref для загрузки исходников (по умолчанию main)
      --with-node          поднять ноду Xray на этом же сервере
      --no-node            не поднимать ноду (только панель)
      --node-port <порт>   публичный порт ноды (по умолчанию 443, с HTTPS — 8443)
      --node-name <имя>    отображаемое имя ноды
      --node-address <адр> адрес ноды для ссылок (по умолчанию публичный IP)
      --seed-demo          загрузить демо-данные (для витрины/теста)
      --admin-user <имя>   имя администратора (по умолчанию admin)
      --admin-password <п> пароль администратора (по умолчанию сгенерируется)
  -y, --yes                не задавать вопросов
      --dry-run            показать план, ничего не менять
      --no-self-update     не включать обновление панели из интерфейса
      --uninstall          удалить панель и контейнеры
  -h, --help               эта справка
  -V, --version            версия установщика

Примеры:
  sudo ./install.sh --domain panel.example.com --with-node
  curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh \\
    | sudo bash -s -- --domain panel.example.com --with-node
EOF
}

# ---------------------------------------------------------------- аргументы ---
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -d|--domain)      DOMAIN="${2:-}"; shift 2 ;;
            --email)          ACME_EMAIL="${2:-}"; shift 2 ;;
            -p|--port)        PANEL_PORT="${2:-}"; PORT_FLAG=1; shift 2 ;;
            --dir)            INSTALL_DIR="${2:-}"; shift 2 ;;
            --ref)            REF="${2:-}"; shift 2 ;;
            --with-node)      NODE_MODE="yes"; shift ;;
            --no-node)        NODE_MODE="no"; shift ;;
            --node-port)      NODE_PORT="${2:-}"; shift 2 ;;
            --node-name)      NODE_NAME="${2:-}"; shift 2 ;;
            --node-address)   NODE_ADDRESS="${2:-}"; shift 2 ;;
            --seed-demo)      SEED_DEMO=1; shift ;;
            --admin-user)     ADMIN_USER="${2:-}"; shift 2 ;;
            --admin-password) ADMIN_PASSWORD="${2:-}"; shift 2 ;;
            -y|--yes)         ASSUME_YES=1; shift ;;
            --dry-run)        DRY_RUN=1; shift ;;
            --uninstall)      UNINSTALL=1; shift ;;
            --no-self-update) SELF_UPDATE=0; shift ;;
            -h|--help)        usage; exit 0 ;;
            -V|--version)     echo "$APP_NAME installer $APP_VERSION"; exit 0 ;;
            *) die "Неизвестный флаг: $1 (см. --help)" ;;
        esac
    done
    if [ -n "$DOMAIN" ]; then
        DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
    fi
    case "$PANEL_PORT" in ''|*[!0-9]*) die "Некорректный порт панели: $PANEL_PORT" ;; esac
}

# ---------------------------------------------------------------- окружение ---
need_root() {
    if [ "$(id -u)" -ne 0 ] && [ "${DFX_ALLOW_NONROOT:-0}" != "1" ]; then
        die "Нужны права root: запустите через sudo (sudo ./install.sh) или от root."
    fi
    if [ "$(id -u)" -ne 0 ]; then
        warn "Режим DFX_ALLOW_NONROOT: установка Docker и /usr/local/bin может не сработать."
    fi
}

detect_os() {
    OS_ID="unknown"; OS_NAME="Linux"
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_NAME="${PRETTY_NAME:-$OS_ID}"
    fi
    PKG=""
    if command -v apt-get >/dev/null 2>&1; then PKG="apt"
    elif command -v dnf >/dev/null 2>&1; then PKG="dnf"
    elif command -v yum >/dev/null 2>&1; then PKG="yum"
    elif command -v apk >/dev/null 2>&1; then PKG="apk"
    fi
    info "Система: $OS_NAME (пакетный менеджер: ${PKG:-не найден})"
}

install_packages() {
    local packages=("$@")
    [ "${#packages[@]}" -eq 0 ] && return 0
    info "Устанавливаю пакеты: ${packages[*]}"
    case "$PKG" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq "${packages[@]}"
            ;;
        dnf) dnf install -y -q "${packages[@]}" ;;
        yum) yum install -y -q "${packages[@]}" ;;
        apk) apk add --no-cache "${packages[@]}" ;;
        *) warn "Пакетный менеджер не определён — пропускаю установку: ${packages[*]}" ;;
    esac
}

ensure_base_tools() {
    local missing=()
    for tool in curl tar gzip; do
        command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        install_packages ca-certificates "${missing[@]}"
    fi
}

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        ok "Docker уже установлен: $(docker --version | cut -d, -f1)"
        return 0
    fi
    if [ "$SKIP_DOCKER_INSTALL" = "1" ]; then
        die "Docker не найден, а установка отключена (DFX_SKIP_DOCKER=1)."
    fi
    step "Установка Docker"
    if command -v curl >/dev/null 2>&1 && curl -fsSL --max-time 60 https://get.docker.com -o /tmp/dfxray-get-docker.sh 2>/dev/null; then
        sh /tmp/dfxray-get-docker.sh || warn "Официальный скрипт Docker завершился с ошибкой, пробую пакеты"
        rm -f /tmp/dfxray-get-docker.sh
    fi
    if ! command -v docker >/dev/null 2>&1; then
        case "$PKG" in
            apt) install_packages docker.io docker-compose-plugin || install_packages docker.io docker-compose-v2 || install_packages docker.io docker-compose ;;
            dnf) install_packages moby-engine docker-compose-plugin || install_packages docker docker-compose ;;
            yum) install_packages docker docker-compose ;;
            apk) install_packages docker docker-cli-compose ;;
            *) die "Не удалось установить Docker. Установите его вручную: https://docs.docker.com/engine/install/" ;;
        esac
    fi
    command -v docker >/dev/null 2>&1 || die "Docker так и не установился."
    systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
    # ждём, пока поднимется демон
    local attempt
    for attempt in $(seq 1 15); do
        docker info >/dev/null 2>&1 && break
        sleep 1
    done
    docker info >/dev/null 2>&1 || die "Демон Docker не запустился. Проверьте: systemctl status docker"
    ok "Docker установлен: $(docker --version | cut -d, -f1)"
}

detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
    else
        info "Устанавливаю Docker Compose plugin"
        case "$PKG" in
            apt) install_packages docker-compose-plugin || install_packages docker-compose-v2 || install_packages docker-compose ;;
            dnf|yum) install_packages docker-compose-plugin || install_packages docker-compose ;;
            apk) install_packages docker-cli-compose ;;
            *) : ;;
        esac
    fi
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
        warn "Используется устаревший docker-compose v1 — рекомендуется плагин v2."
    else
        die "Docker Compose не найден. Установите плагин docker-compose-plugin."
    fi
    ok "Compose: $("${COMPOSE[@]}" version --short 2>/dev/null | head -1)"
}

port_busy() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}$"
    else
        return 1
    fi
}

detect_public_ip() {
    local ip=""
    if command -v curl >/dev/null 2>&1; then
        for service in https://api.ipify.org https://ifconfig.me/ip https://icanhazip.com; do
            ip="$(curl -fsS --max-time 4 "$service" 2>/dev/null | tr -dc '0-9a-fA-F.:' || true)"
            case "$ip" in
                169.254.*|127.*|"") continue ;;
            esac
            if [ -n "$ip" ]; then printf '%s' "$ip"; return 0; fi
        done
    fi
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || true
    printf '%s' "${ip:-127.0.0.1}"
}

gen_password() {
    local value=""
    if command -v openssl >/dev/null 2>&1; then
        value="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
    fi
    if [ -z "$value" ]; then
        value="$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -dc 'A-Za-z0-9' | cut -c1-20)"
    fi
    printf '%s' "${value:-ChangeMeNow12345}"
}

# ---------------------------------------------------------------- исходники ---
script_dir() {
    local source="${BASH_SOURCE[0]:-}"
    if [ -n "$source" ] && [ -f "$source" ]; then
        (cd "$(dirname "$source")" >/dev/null 2>&1 && pwd)
    else
        pwd
    fi
}

fetch_sources() {
    step "Исходники"
    local source_dir
    source_dir="$(script_dir)"
    mkdir -p "$INSTALL_DIR"

    if [ -f "$source_dir/docker-compose.yml" ] && [ -d "$source_dir/app" ]; then
        if [ "$source_dir" = "$INSTALL_DIR" ]; then
            ok "Использую текущий каталог: $INSTALL_DIR"
        else
            info "Копирую файлы из $source_dir в $INSTALL_DIR"
            tar -C "$source_dir" -cf - \
                --exclude=.git --exclude=data --exclude=.env --exclude=.env.bak \
                --exclude=__pycache__ --exclude=node_modules --exclude=.credentials \
                --exclude=.ruff_cache --exclude=.pytest_cache --exclude=.mypy_cache --exclude='*.db*' \
                --exclude=Caddyfile . 2>/dev/null | tar -C "$INSTALL_DIR" -xf -
            ok "Файлы скопированы"
        fi
        return 0
    fi

    info "Скачиваю DF_Xray $REF с GitHub"
    local archive="/tmp/dfxray-src-$$.tar.gz"
    local url="" candidate
    for candidate in \
        "https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF" \
        "https://codeload.github.com/$REPO/tar.gz/refs/tags/$REF" \
        "https://codeload.github.com/$REPO/tar.gz/$REF"; do
        if curl -fsSL --max-time 120 "$candidate" -o "$archive"; then
            url="$candidate"
            break
        fi
    done
    [ -n "$url" ] || die "Не удалось скачать исходники ($REPO, ref=$REF)."
    tar -xzf "$archive" -C "$INSTALL_DIR" --strip-components=1
    rm -f "$archive"
    [ -f "$INSTALL_DIR/docker-compose.yml" ] || die "Архив не содержит docker-compose.yml."
    ok "Исходники загружены в $INSTALL_DIR"
}

# Код должен принадлежать пользователю панели (uid 1000 в образе), иначе кнопка
# «Обновить» из интерфейса не сможет переписать файлы.
grant_self_update() {
    [ "${SELF_UPDATE:-1}" = "1" ] || return 0
    [ "$(id -u)" = "0" ] || return 0
    local paths=(app static node bin docs install.sh docker-compose.yml \
                 docker-compose.selfupdate.yml Dockerfile pyproject.toml Makefile README.md LICENSE)
    local item present=()
    for item in "${paths[@]}"; do
        [ -e "$INSTALL_DIR/$item" ] && present+=("$INSTALL_DIR/$item")
    done
    [ ${#present[@]} -gt 0 ] || return 0
    chown -R 1000:1000 "${present[@]}" 2>/dev/null || true
    info "Права на код переданы uid 1000 — самообновление из панели включено"
}

# ---------------------------------------------------------------- конфигурация ---
read_existing_env() {
    if [ -f "$INSTALL_DIR/.env" ]; then
        EXISTING_ENV=1
        local existing_pass existing_url existing_user existing_port existing_node_port
        existing_pass="$(grep -E '^DFX_ADMIN_PASSWORD=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
        existing_url="$(grep -E '^DFX_BASE_URL=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
        existing_user="$(grep -E '^DFX_ADMIN_USERNAME=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
        existing_port="$(grep -E '^PANEL_PORT=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
        existing_node_port="$(grep -E '^NODE_PORT=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
        EXISTING_URL="$existing_url"
        if [ -n "$existing_pass" ] && [ -z "$ADMIN_PASSWORD" ]; then ADMIN_PASSWORD="$existing_pass"; fi
        if [ -z "$DOMAIN" ] && [ -n "$existing_url" ] && [[ "$existing_url" == https://* ]]; then
            DOMAIN="${existing_url#https://}"; DOMAIN="${DOMAIN%%/*}"
        fi
        if [ -n "$existing_user" ] && [ "$ADMIN_USER" = "admin" ]; then ADMIN_USER="$existing_user"; fi
        if [ "$PORT_FLAG" = "0" ] && [ -n "$existing_port" ]; then PANEL_PORT="$existing_port"; fi
        if [ -z "$NODE_PORT" ] && [ -n "$existing_node_port" ]; then NODE_PORT="$existing_node_port"; fi
    fi
}

ask_settings() {
    local interactive=0
    if [ -t 0 ] && [ -t 1 ] && [ "$ASSUME_YES" != "1" ] && [ "$DRY_RUN" != "1" ]; then interactive=1; fi

    if [ "$interactive" = "1" ] && [ -z "$DOMAIN" ]; then
        printf '\n%sДомен для автоматического HTTPS%s (Enter — без домена, панель на IP:порт): ' \
            "$C_BOLD" "$C_RESET"
        read -r DOMAIN_INPUT || DOMAIN_INPUT=""
        DOMAIN="${DOMAIN_INPUT// /}"
        DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
    fi

    if [ -n "$DOMAIN" ] && ! printf '%s' "$DOMAIN" | grep -Eq '^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$'; then
        die "Похоже, домен указан неверно: $DOMAIN"
    fi

    if [ -z "$ADMIN_PASSWORD" ]; then
        ADMIN_PASSWORD="$(gen_password)"
        if [ "$interactive" = "1" ]; then
            printf '%sПароль администратора%s (Enter — сгенерированный): ' "$C_BOLD" "$C_RESET"
            read -rs ADMIN_PASSWORD_INPUT || ADMIN_PASSWORD_INPUT=""
            printf '\n'
            if [ -n "$ADMIN_PASSWORD_INPUT" ]; then ADMIN_PASSWORD="$ADMIN_PASSWORD_INPUT"; fi
        fi
    fi
    [ "${#ADMIN_PASSWORD}" -ge 8 ] || die "Пароль должен быть не короче 8 символов."
    case "$ADMIN_PASSWORD" in
        *[\ \#\"\'\$]*) die "В пароле не должно быть пробелов, кавычек, # и \$." ;;
    esac

    if [ "$NODE_MODE" = "ask" ]; then
        if [ "$interactive" = "1" ]; then
            printf '\n%sПоставить ноду Xray на этом же сервере?%s [Y/n]: ' "$C_BOLD" "$C_RESET"
            local answer=""
            read -r answer || answer=""
            case "$answer" in
                n|N|no|No|нет|Нет) NODE_MODE="no" ;;
                *) NODE_MODE="yes" ;;
            esac
        else
            NODE_MODE="no"
        fi
    fi

    if [ "$NODE_MODE" = "yes" ]; then
        if [ -z "$NODE_PORT" ]; then
            if [ -n "$DOMAIN" ] || port_busy 443; then NODE_PORT=8443; else NODE_PORT=443; fi
        fi
        if port_busy "$NODE_PORT"; then
            warn "Порт $NODE_PORT уже занят. Укажите свободный: --node-port <порт>"
            if [ "$interactive" = "1" ]; then
                printf 'Порт ноды: '
                read -r NODE_PORT_INPUT || NODE_PORT_INPUT=""
                [ -n "$NODE_PORT_INPUT" ] && NODE_PORT="$NODE_PORT_INPUT"
            fi
        fi
        if port_busy "$NODE_PORT"; then
            die "Порт $NODE_PORT всё ещё занят — освободите его или укажите другой."
        fi
        if [ -z "$NODE_ADDRESS" ]; then
            NODE_ADDRESS="$(detect_public_ip)"
        fi
        if [ -z "$NODE_NAME" ]; then
            NODE_NAME="DF · $(hostname -s 2>/dev/null || echo node)"
        fi
    fi

    if [ -n "$DOMAIN" ]; then
        PANEL_BIND="127.0.0.1"
        PANEL_URL="https://$DOMAIN"
    else
        PANEL_BIND="0.0.0.0"
        if [ -n "$EXISTING_URL" ] && [ "$PORT_FLAG" = "0" ]; then
            PANEL_URL="$EXISTING_URL"
        else
            local ip
            ip="$(detect_public_ip)"
            PANEL_URL="http://${ip}:${PANEL_PORT}"
        fi
    fi
}

backup_env() {
    if [ -f "$INSTALL_DIR/.env" ]; then
        local backup
        backup="$INSTALL_DIR/.env.bak.$(date +%Y%m%d-%H%M%S)"
        cp -a "$INSTALL_DIR/.env" "$backup"
        info "Старый .env сохранён как $(basename "$backup")"
    fi
}

write_env() {
    step "Конфигурация"
    backup_env
    local compose_profiles=""
    [ -n "$DOMAIN" ] && compose_profiles="tls"
    local node_token=""
    if [ -f "$INSTALL_DIR/.env" ]; then
        node_token="$(grep -E '^NODE_TOKEN=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
    fi
    umask 077
    cat > "$INSTALL_DIR/.env" <<EOF
# Сгенерировано установщиком DF_Xray $(date '+%Y-%m-%d %H:%M:%S')
# Панель
PANEL_PORT=$PANEL_PORT
PANEL_BIND=$PANEL_BIND
DFX_BASE_URL=$PANEL_URL
DFX_ADMIN_USERNAME=$ADMIN_USER
DFX_ADMIN_PASSWORD=$ADMIN_PASSWORD
DFX_SESSION_TTL_HOURS=168
DFX_SEED_DEMO=$SEED_DEMO
DFX_TRUST_PROXY=1

# HTTPS через Caddy (профиль tls)
SELF_UPDATE=${SELF_UPDATE:-1}
COMPOSE_PROFILES=$compose_profiles
PANEL_DOMAIN=$DOMAIN
ACME_EMAIL=$ACME_EMAIL

# Нода
NODE_TOKEN=$node_token
NODE_PORT=${NODE_PORT:-443}
NODE_POLL=30
NODE_LOG_LEVEL=info
XRAY_VERSION=${XRAY_VERSION:-$XRAY_VERSION_DEFAULT}
PANEL_INTERNAL_URL=http://panel:8000
EOF
    umask 022
    chmod 600 "$INSTALL_DIR/.env"
    ok ".env записан (пароль сохранён в $INSTALL_DIR/.credentials)"

    {
        printf 'URL=%s\n' "$PANEL_URL"
        printf 'USER=%s\n' "$ADMIN_USER"
        printf 'PASSWORD=%s\n' "$ADMIN_PASSWORD"
        printf 'DATE=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    } > "$INSTALL_DIR/.credentials"
    chmod 600 "$INSTALL_DIR/.credentials"
}

write_caddyfile() {
    [ -n "$DOMAIN" ] || return 0
    step "HTTPS (Caddy)"
    {
        if [ -n "$ACME_EMAIL" ]; then
            printf '{\n    email %s\n}\n\n' "$ACME_EMAIL"
        fi
        printf '%s {\n' "$DOMAIN"
        printf '    encode zstd gzip\n'
        printf '    header {\n        Strict-Transport-Security "max-age=31536000; includeSubDomains"\n    }\n'
        printf '    reverse_proxy panel:8000\n'
        printf '}\n'
    } > "$INSTALL_DIR/Caddyfile"
    chmod 644 "$INSTALL_DIR/Caddyfile"
    ok "Caddyfile создан для $DOMAIN"
}

# ---------------------------------------------------------------- запуск ---
compose() {
    local files=(-f "$INSTALL_DIR/docker-compose.yml")
    # Самообновление панели из интерфейса: код монтируется из каталога установки.
    if [ "$SELF_UPDATE" = "1" ] && [ -f "$INSTALL_DIR/docker-compose.selfupdate.yml" ]; then
        files+=(-f "$INSTALL_DIR/docker-compose.selfupdate.yml")
    fi
    "${COMPOSE[@]}" --project-directory "$INSTALL_DIR" "${files[@]}" "$@"
}

start_stack() {
    step "Сборка и запуск"
    cd "$INSTALL_DIR"
    grant_self_update
    info "Собираю образ панели (первый раз это занимает 1–2 минуты)"
    compose build panel
    compose up -d panel
    if [ -n "$DOMAIN" ]; then
        compose up -d caddy
    fi
    ok "Контейнеры запущены"
}

wait_health() {
    step "Проверка панели"
    local attempt cid status
    for attempt in $(seq 1 60); do
        if curl -fsS --max-time 3 "http://127.0.0.1:${PANEL_PORT}/healthz" >/dev/null 2>&1; then
            ok "Панель отвечает (попытка $attempt)"
            return 0
        fi
        # если контейнер упал — не ждём две минуты впустую
        if [ $((attempt % 4)) -eq 0 ]; then
            cid="$(compose ps -q panel 2>/dev/null | head -1 || true)"
            if [ -n "$cid" ] && command -v docker >/dev/null 2>&1; then
                status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
                case "$status" in
                    exited|dead)
                        warn "Контейнер панели остановился — последние строки лога:"
                        compose logs --tail=30 panel >&2 || true
                        return 1
                        ;;
                esac
            fi
        fi
        sleep 2
    done
    warn "Панель не ответила за 2 минуты. Проверьте: dfxray logs panel"
    return 1
}

create_node() {
    [ "$NODE_MODE" = "yes" ] || return 0
    step "Нода Xray"
    local existing_token
    existing_token="$(grep -E '^NODE_TOKEN=' "$INSTALL_DIR/.env" | head -1 | cut -d= -f2- || true)"
    if [ -n "$existing_token" ]; then
        info "Нода уже настроена — перезапускаю контейнер агента"
        compose up -d node-de
        ok "Нода запущена (токен сохранён)"
        return 0
    fi
    local address="${NODE_ADDRESS:-$(detect_public_ip)}"
    local name="${NODE_NAME:-DF · node}"
    info "Создаю ноду «$name» ($address:$NODE_PORT)"
    local token
    if token="$(compose exec -T panel python -m app node-add \
            --name "$name" --address "$address" --port "$NODE_PORT" \
            --print-token 2>/dev/null)" && [ -n "$token" ]; then
        ok "Нода создана, токен получен"
    else
        warn "Не удалось создать ноду автоматически. Добавьте её в панели: Ноды → Добавить ноду."
        return 0
    fi
    set_env_value NODE_TOKEN "$token"
    set_env_value NODE_PORT "$NODE_PORT"
    info "Запускаю контейнер ноды (порт $NODE_PORT)"
    compose up -d node-de
    ok "Нода запущена, конфиг подтянется в течение 30 секунд"
}

set_env_value() {
    local key="$1" value="$2" file="$INSTALL_DIR/.env"
    if grep -qE "^${key}=" "$file"; then
        # экранируем спецсимволы для sed
        local escaped
        escaped="$(printf '%s' "$value" | sed -e 's/[\/&]/\\&/g')"
        sed -i "s/^${key}=.*/${key}=${escaped}/" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

install_cli() {
    step "Команда управления"
    mkdir -p "$CONF_DIR" "$BIN_DIR"
    if [ ! -f "$INSTALL_DIR/bin/dfxray" ]; then
        info "В архиве нет bin/dfxray — скачиваю отдельно"
        curl -fsSL --max-time 60 \
            "https://raw.githubusercontent.com/$REPO/$REF/bin/dfxray" \
            -o "$INSTALL_DIR/bin/dfxray" || warn "Не удалось скачать CLI — команда dfxray не установлена"
    fi
    if [ -f "$INSTALL_DIR/bin/dfxray" ]; then
        install -m 0755 "$INSTALL_DIR/bin/dfxray" "$BIN_DIR/dfxray"
    fi
    cat > "$CONF_DIR/install.conf" <<EOF
# DF_Xray Panel — параметры установки (используется командой dfxray)
DFX_HOME="$INSTALL_DIR"
PANEL_PORT="$PANEL_PORT"
PANEL_BIND="$PANEL_BIND"
PANEL_URL="$PANEL_URL"
PANEL_DOMAIN="$DOMAIN"
PANEL_USER="$ADMIN_USER"
COMPOSE_CMD="$(printf '%s ' "${COMPOSE[@]}")"
EOF
    chmod 644 "$CONF_DIR/install.conf"
    if [ -x "$BIN_DIR/dfxray" ] || [ -f "$BIN_DIR/dfxray" ]; then
        ok "Установлена команда: $BIN_DIR/dfxray (help — список команд)"
    fi
}

firewall_hint() {
    local ports=""
    if [ -n "$DOMAIN" ]; then ports="80/tcp 443/tcp"; else ports="$PANEL_PORT/tcp"; fi
    [ "$NODE_MODE" = "yes" ] && ports="$ports $NODE_PORT/tcp"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        warn "UFW включён — откройте порты: ufw allow ${ports// /,}"
    fi
}

print_summary() {
    local elapsed=$(( $(date +%s) - STARTED_AT ))
    local node_line=""
    if [ "$NODE_MODE" = "yes" ]; then
        node_line="Нода:       Xray на порту $NODE_PORT (токен в $INSTALL_DIR/.env)"
    else
        node_line="Нода:       не устанавливалась (Ноды → Добавить ноду)"
    fi
    printf '\n%s╭────────────────────────────────────────────────────────────╮%s\n' "$C_GREEN" "$C_RESET"
    printf '%s│%s  %sDF_Xray Panel установлена за %s с%s\n' "$C_GREEN" "$C_RESET" "$C_BOLD" "$elapsed" "$C_RESET"
    printf '%s╰────────────────────────────────────────────────────────────╯%s\n' "$C_GREEN" "$C_RESET"
    printf '\n  %sПанель:%s     %s\n' "$C_BOLD" "$C_RESET" "$PANEL_URL"
    printf '  %sЛогин:%s      %s\n' "$C_BOLD" "$C_RESET" "$ADMIN_USER"
    printf '  %sПароль:%s     %s\n' "$C_BOLD" "$C_RESET" "$ADMIN_PASSWORD"
    printf '  %sКаталог:%s    %s\n' "$C_BOLD" "$C_RESET" "$INSTALL_DIR"
    printf '  %s%s%s\n' "$C_BOLD" "$node_line" "$C_RESET"
    if [ -z "$DOMAIN" ]; then
        printf '\n  %sБез домена панель работает по HTTP.%s Для HTTPS перезапустите установщик с --domain.\n' \
            "$C_YELLOW" "$C_RESET"
    fi
    printf '\n  Управление:    dfxray status | logs | password | backup | update\n'
    printf '  Файл с доступами: %s\n' "$INSTALL_DIR/.credentials"
    printf '\n  Следующие шаги:\n'
    printf '   1. Откройте %s и смените пароль (Настройки → Безопасность).\n' "$PANEL_URL"
    if [ "$NODE_MODE" != "yes" ]; then
        printf '   2. Добавьте ноду: Ноды → Добавить ноду → запустите агент с токеном.\n'
    else
        printf '   2. Создайте пользователя: Пользователи → Новый пользователь → QR-код.\n'
    fi
    printf '   3. Проверьте статус: dfxray status\n\n'
    firewall_hint
}

# ---------------------------------------------------------------- удаление ---
uninstall() {
    step "Удаление DF_Xray Panel"
    local conf="$CONF_DIR/install.conf"
    if [ -f "$conf" ]; then
        # shellcheck disable=SC1090
        . "$conf"
        INSTALL_DIR="${DFX_HOME:-$INSTALL_DIR}"
    fi
    if [ "$ASSUME_YES" != "1" ]; then
        printf 'Удалить контейнеры панели из %s? Данные в томе сохранятся. [y/N]: ' "$INSTALL_DIR"
        local answer=""
        read -r answer || answer=""
        case "$answer" in y|Y|yes|Yes|да|Да) ;; *) info "Отменено"; exit 0 ;; esac
    fi
    if [ -f "$INSTALL_DIR/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
        if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose); else COMPOSE=(docker-compose); fi
        compose down --remove-orphans || warn "Не удалось остановить контейнеры"
        ok "Контейнеры остановлены и удалены (том с данными сохранён)"
    fi
    rm -f "$BIN_DIR/dfxray"
    rm -rf "$CONF_DIR"
    info "Команда dfxray и конфигурация удалены."
    info "Данные остались в docker-томе и в $INSTALL_DIR (удалите вручную при необходимости)."
    rm -rf "${INSTALL_DIR:?}/app" "${INSTALL_DIR:?}/node" "${INSTALL_DIR:?}/static" \
        "${INSTALL_DIR:?}/docs" "${INSTALL_DIR:?}/tests" "${INSTALL_DIR:?}/bin" 2>/dev/null || true
    ok "Готово. Полное удаление данных: docker volume rm dfxray_dfxray-data && rm -rf $INSTALL_DIR"
}

# ---------------------------------------------------------------- main ---
dry_run_report() {
    cat <<EOF

${C_BOLD}План установки DF_Xray Panel $APP_VERSION${C_RESET}

  Каталог:        $INSTALL_DIR
  Ref:            $REF
  Домен:          ${DOMAIN:-— (без HTTPS, панель на IP)}
  Порт панели:    $PANEL_PORT (bind: $PANEL_BIND)
  Публичный URL:  $PANEL_URL
  Администратор:  $ADMIN_USER / $ADMIN_PASSWORD
  Нода Xray:      $NODE_DISPLAY
  Демо-данные:    $SEED_DEMO

Шаги, которые будут выполнены:
  1. Проверка системы и установка пакетов (curl, tar, gzip, openssl)
  2. Установка Docker Engine и Compose plugin (если их нет)
  3. Загрузка исходников в $INSTALL_DIR
  4. Генерация .env и Caddyfile (для HTTPS)
  5. Сборка образа и запуск контейнеров
  6. Создание ноды и запуск агента (если --with-node)
  7. Установка команды dfxray в /usr/local/bin

Ничего не изменено (--dry-run).
EOF
}

main() {
    parse_args "$@"
    printf '%s%s%s · установщик %s\n' "$C_BOLD$C_VIOLET" "$APP_NAME" "$C_RESET" "$APP_VERSION"

    if [ "$UNINSTALL" = "1" ]; then
        need_root
        uninstall
        return 0
    fi

    detect_os

    # Значения по умолчанию для dry-run и валидации
    read_existing_env
    ask_settings

    if [ "$NODE_MODE" = "yes" ]; then
        NODE_DISPLAY="да — ${NODE_NAME:-DF · $(hostname -s 2>/dev/null || echo node)} @ ${NODE_ADDRESS:-?}:${NODE_PORT:-443}"
    else
        NODE_DISPLAY="нет (только панель)"
    fi

    if [ "$DRY_RUN" = "1" ]; then
        dry_run_report
        return 0
    fi

    need_root

    if [ "$EXISTING_ENV" = "1" ]; then
        info "Найдена существующая установка — обновляю файлы и перезапускаю сервисы"
    fi

    ensure_base_tools
    install_docker
    detect_compose
    fetch_sources
    write_env
    write_caddyfile
    install_cli
    start_stack
    wait_health || true
    create_node
    print_summary
}

if [ "${DFX_SKIP_MAIN:-0}" != "1" ]; then
    main "$@"
fi
