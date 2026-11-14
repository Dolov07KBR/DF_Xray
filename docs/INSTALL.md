# Установка DF_Xray Panel на VPS

Документ описывает установщик `install.sh`: что он делает, какие флаги принимает,
как обновляться и как всё удалить.

## Быстрая установка

```bash
curl -fsSL https://raw.githubusercontent.com/Dolov07KBR/DF_Xray/main/install.sh | sudo bash
```

Скрипт задаст два вопроса — домен (можно пропустить) и пароль администратора
(можно оставить пустым, тогда пароль сгенерируется) — и всё сделает сам.

В конце установки на экране появятся адрес панели, логин, пароль, путь установки
и подсказки по следующему шагу.

## Требования

- Linux: Ubuntu 20.04+, Debian 11+, CentOS/RHEL 8+, Fedora, AlmaLinux, Rocky, Alpine.
- root-доступ (или `sudo`).
- 1 CPU, 512 МБ RAM, 2 ГБ диска — минимум; с нодой Xray — от 1 ГБ RAM.
- Открытые порты: `80/tcp` и `443/tcp` (с доменом), `8000/tcp` (без домена),
  выбранный порт ноды (по умолчанию `443`, с доменом — `8443`).
- Домен, если нужен автоматический HTTPS: A-запись домена должна указывать на IP сервера
  **до** запуска установщика.

## Установка с флагами

При запуске через `curl | bash` аргументы передаются после `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/Dolov07KBR/DF_Xray/main/install.sh \
  | sudo bash -s -- --domain panel.example.com --with-node
```

Из клонированного репозитория — обычным вызовом:

```bash
git clone https://github.com/Dolov07KBR/DF_Xray.git
cd DF_Xray
sudo ./install.sh --domain panel.example.com --with-node
```

### Флаги

| Флаг | Значение | По умолчанию |
| --- | --- | --- |
| `-d, --domain <домен>` | домен для HTTPS; панель слушает только `127.0.0.1`, снаружи — Caddy | нет (HTTP на IP) |
| `--email <адрес>` | e-mail для Let's Encrypt | нет |
| `-p, --port <порт>` | порт панели без домена | `8000` |
| `--dir <путь>` | каталог установки | `/opt/dfxray` |
| `--ref <ref>` | ветка или тег для загрузки исходников | `main` |
| `--with-node` | поднять ноду Xray на этом же сервере | спрашивает |
| `--no-node` | только панель | спрашивает |
| `--node-port <порт>` | публичный порт ноды | `443`, с доменом `8443` |
| `--node-name <имя>` | имя ноды в панели | `DF · <hostname>` |
| `--node-address <адрес>` | адрес в ссылках подписки | публичный IP сервера |
| `--admin-user <имя>` | логин администратора | `admin` |
| `--admin-password <пароль>` | пароль администратора | генерируется |
| `--seed-demo` | загрузить демо-данные | выключено |
| `-y, --yes` | не задавать вопросов | выключено |
| `--dry-run` | показать план и выйти | — |
| `--uninstall` | удалить панель | — |
| `-h, --help` | справка | — |
| `-V, --version` | версия установщика | — |

### Переменные окружения

Те же значения можно задать переменными: `DFX_DOMAIN`, `DFX_EMAIL`, `DFX_PANEL_PORT`,
`DFX_ADMIN_USERNAME`, `DFX_ADMIN_PASSWORD`, `DFX_NODE_MODE` (`ask|yes|no`), `DFX_NODE_PORT`,
`DFX_INSTALL_DIR`, `DFX_REF`, `DFX_SEED_DEMO`, `DFX_REPO`, `DFX_SKIP_DOCKER`,
`DFX_BIN_DIR`, `DFX_CONF_DIR`, `DFX_ALLOW_NONROOT` (для тестов).

## Что делает установщик

1. Определяет дистрибутив и пакетный менеджер, ставит `curl tar gzip openssl`.
2. Ставит Docker Engine и Compose plugin (официальный скрипт `get.docker.com`,
   при неудаче — пакеты дистрибутива).
3. Загружает исходники: из локального каталога, если рядом с `install.sh` есть проект,
   иначе — архивом с GitHub (`codeload`, ref из `--ref`).
4. Пишет `.env` (права `600`) и `.credentials` с реквизитами.
5. С доменом — создаёт `Caddyfile`, включает профиль `tls` и поднимает Caddy,
   который сам получает сертификат Let's Encrypt.
6. Собирает образ панели и запускает контейнеры, ждёт ответа `/healthz`.
7. С `--with-node` создаёт ноду через CLI панели, записывает `NODE_TOKEN` в `.env`
   и запускает агент `node-de`.
8. Ставит команду `dfxray` в `/usr/local/bin` и файл параметров в `/etc/dfxray/install.conf`.
9. Печатает итоговые реквизиты и подсказки.

Установка идемпотентна: повторный запуск сохраняет пароль, домен и токен ноды,
перезаписывает файлы и перезапускает контейнеры. Старый `.env` сохраняется
рядом как `.env.bak.<дата>`.

## HTTPS

С доменом установщик генерирует `Caddyfile`:

```caddyfile
panel.example.com {
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }
    reverse_proxy panel:8000
}
```

Caddy слушает `80/443`, сам получает и продлевает сертификат. Панель при этом
публикуется только на `127.0.0.1`, а `DFX_BASE_URL` получает значение
`https://<домен>` — этот адрес попадает в ссылки подписок.

Добавить HTTPS к уже установленной панели:

```bash
sudo /opt/dfxray/install.sh --domain panel.example.com --yes
```

(установщик подхватит сохранённый пароль из `.env`).

## Команда управления `dfxray`

| Команда | Что делает |
| --- | --- |
| `dfxray status` | контейнеры, доступность панели, состояние ноды |
| `dfxray up` / `down` / `restart` | запуск, остановка, перезапуск |
| `dfxray logs [сервис] [-f]` | логи панели, ноды или Caddy |
| `dfxray password [новый]` | смена пароля администратора (без аргумента — генерация) |
| `dfxray backup [файл]` | консистентная копия SQLite-базы |
| `dfxray update [--ref ref]` | обновление до свежих исходников |
| `dfxray url` | адрес панели |
| `dfxray shell` | shell внутри контейнера панели |
| `dfxray version` | версия панели |

## Обновление

```bash
dfxray backup                 # сначала копия базы
sudo dfxray update            # те же флаги, что при установке
```

Обновление — это повторный запуск установщика: исходники перезаписываются,
данные в томе `dfxray-data` и `/opt/dfxray/.env` не трогаются.

## Удаление

```bash
sudo dfxray uninstall              # или: sudo /opt/dfxray/install.sh --uninstall
```

Останавливает и удаляет контейнеры, убирает `dfxray` и `/etc/dfxray`.
База в docker-томе и `.env` при этом сохраняются. Полное удаление:

```bash
docker volume rm dfxray_dfxray-data
sudo rm -rf /opt/dfxray
```

## Диагностика

| Симптом | Что проверить |
| --- | --- |
| «Нужны права root» | запускать через `sudo` |
| Docker не установился | `DFX_SKIP_DOCKER=1` + установить Docker вручную |
| Панель не открывается | `dfxray status`, `dfxray logs panel`, firewall (`ufw allow 8000`) |
| HTTPS не выдаётся | A-запись домена, порты 80/443, `dfxray logs caddy` |
| Порт ноды занят | `ss -ltnp`, затем `--node-port <свободный>` |
| Ссылки подписок с неверным адресом | проверить `DFX_BASE_URL` в `.env` и Настройки → Общие |
| Забыт пароль | `sudo dfxray password новый-пароль` |

Логи установки: `docker compose -f /opt/dfxray/docker-compose.yml logs --tail=100`.
Состояние базы: `docker compose exec panel python -m app check`.

## Безопасность

- `.env` и `.credentials` создаются с правами `600`, пароль администратора не логируется.
- Без домена панель доступна по HTTP — используйте домен с HTTPS для публичного сервера.
- Firewall: открывайте только нужные порты; панель с доменом слушает `127.0.0.1`.
- Сразу после установки смените пароль в интерфейсе (Настройки → Безопасность),
  если он был сгенерирован автоматически.
