# DF_Xray Panel

Лёгкая панель управления [Xray-core](https://github.com/XTLS/Xray-core) в стиле **DF**: тёмный интерфейс,
подписки, QR-коды, лимиты трафика и срока, мульти-ноды и Docker Compose — без единой внешней
Python-зависимости.

> Один сервер → SQLite → ноды Xray по pull-модели. Захотите ещё ноду — добавляете её в панели
> и поднимаете контейнер с токеном, конфиг прилетит сам.

[![license](https://img.shields.io/badge/license-GPL--3.0--only-7c5cff.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-3ea8ff.svg)](https://www.python.org/)
![no dependencies](https://img.shields.io/badge/dependencies-none-2ee6a8.svg)

---

## Содержание

- [Возможности](#возможности)
- [Скриншоты](#скриншоты)
- [Быстрый старт](#быстрый-старт)
- [Первая настройка](#первая-настройка)
- [Автонастройка ноды и выбор SNI](#автонастройка-ноды-и-выбор-sni)
- [Протоколы и конфиги Xray](#протоколы-и-конфиги-xray)
- [Метрики: процессор и память](#метрики-процессор-и-память)
- [Управление Xray из панели](#управление-xray-из-панели)
- [Telegram-бот продаж](#telegram-бот-продаж)
- [Как подключить ноду](#как-подключить-ноду)
- [Мультисервер](docs/MULTISERVER.md)
- [Подписки и QR-коды](#подписки-и-qr-коды)
- [Лимиты и сроки](#лимиты-и-сроки)
- [Архитектура](#архитектура)
- [Настройки и переменные окружения](#настройки-и-переменные-окружения)
- [Клиентская часть API](#клиентская-часть-api)
- [Безопасность](#безопасность)
- [2FA, API-токены и TLS](docs/SECURITY.md)
- [Уведомления](docs/NOTIFICATIONS.md)
- [Drain, миграция клиентов и латентность](docs/OPERATIONS.md)
- [Нагрузочное тестирование](docs/LOADTEST.md)
- [Бэкапы и обслуживание](#бэкапы-и-обслуживание)
- [Разработка и тесты](#разработка-и-тесты)
- [Структура проекта](#структура-проекта)
- [Дорожная карта](#дорожная-карта)
- [Лицензия](#лицензия)

## Возможности

**Навигация**
- Минимальное боковое меню: `Дашборд / Клиенты / Узлы / Подписки / Настройки`.
  Всё остальное (входящие, группы, хосты, исходящие, маршрутизация, конфиги Xray,
  агенты, журнал, API) — плитками в «Настройки → Разделы панели».
- Командная палитра ищет по разделам, клиентам, нодам и действиям; активный пункт
  подсвечивается по текущему адресу, старые ссылки (`#/users`, `#/outbounds`…)
  продолжают работать через редиректы.

**Пользователи и доступы**
- CRUD пользователей, UUID, flow `xtls-rprx-vision`, отметка лимита устройств
  (панель хранит и показывает его сама — в конфиг Xray это поле не уходит).
- Лимит трафика и дата окончания подписки; статусы `активен / лимит / истёк / отключён`
  считаются на лету — никаких «залипших» блокировок.
- Массовые действия: продлить, сбросить трафик, перевыпустить UUID или токен подписки,
  включить/отключить, удалить.
- Поиск, фильтры по статусу, сортировка, экспорт в CSV.

**Наблюдаемость**
- Графики процессора и памяти панели на дашборде (сэмплер раз в 20 секунд, история в SQLite),
  CPU/RAM/uptime каждой ноды из heartbeat агента.
- `GET /api/metrics?node_id=0&minutes=60` — серия, текущие значения и железо хоста.

**Управление нодами**
- Команды агенту из панели: перезапуск Xray, `xray -test`, перезапуск агента.
  Кнопки — в карточке ноды, статус — тостом после ответа агента.

**Продажи**
- Telegram-бот прямо в панели: тарифы, Telegram Stars или ручная оплата,
  выдача подписки после оплаты, одноразовый триал, админ-команды `/stats`, `/orders`,
  `/approve`, `/deny`.

**Подписки**
- Один адрес на пользователя: `/sub/<token>` — base64-список `vless:// / vmess:// / trojan://`.
- Заголовки `subscription-userinfo`, `profile-title`, `profile-update-interval`,
  `profile-web-page-url`, `support-url` — клиенты показывают расход и дату окончания.
- Публичная страница подписки `/sub/<token>/page`: тёмная витрина с QR, кольцом трафика,
  чипами протоколов и кнопками копирования.
- QR-коды генерируются на сервере (SVG и PNG) — без JS-библиотек и внешних сервисов.

**Мультисервер**
- Любое число серверов Xray под одной панелью: клиенты, лимиты и статистика общие.
- Онбординг нового сервера одной командой: панель отдаёт bash-скрипт с токеном
  установки, который ставит Xray + агент как systemd-сервис (или Docker /
  docker-compose — на выбор).
- Агент присылает heartbeat каждые 30 секунд: версия Xray и агента, состояние
  процесса, uptime, LA1, память и ревизию применённого конфига; ошибки `xray -test`
  видны в карточке сервера.
- Раздел «Агенты нод» — таблица всех серверов; дашборд — трафик по серверам и
  предупреждение о недоступных нодах. Клиента можно ограничить отдельными
  серверами. Подробности: [docs/MULTISERVER.md](docs/MULTISERVER.md).

**Группы и маршрутизация**
- Группы клиентов с цветом и заметкой: фильтр в списке пользователей, бейдж в карточке,
  назначение группы прямо из формы клиента.
- Исходящие (SOCKS / HTTP / direct / block) попадают в блок `outbounds` конфига Xray;
  основной исходящий выбирается в разделе «Маршрутизация».
- Раздел «Хосты» собирает домены-маски из входящих и запускает для них сканер.

**Ноды**
- Мульти-ноды: VLESS / VMess / Trojan, транспорт TCP / WebSocket / gRPC / XHTTP / HTTP2,
  безопасность Reality / TLS / без шифрования.
- **Автонастройка по протоколам**: в форме сервера восемь готовых сценариев
  (Reality · Vision, Reality · XHTTP, Reality · gRPC, TLS · WebSocket, TLS · gRPC,
  VMess · TLS + WS, Trojan · TLS, без шифрования) — пресет заполняет протокол,
  транспорт, безопасность, порт, `path` и SNI, а серверная валидация не даст собрать
  несовместимую комбинацию (например Vision-flow у VMess или Reality по WebSocket).
- **Список SNI на выбор**: 13 встроенных доменов-доноров с описаниями, поиск по списку,
  кнопка «Проверить» (TLS 1.3 / ALPN / задержка прямо в форме), случайный SNI одной
  кнопкой и добавление своего домена — он сохраняется в настройках панели и сразу
  доступен во всех формах.
- Конфиг Xray генерируется на лету из данных панели: клиенты, Reality-ключи, сертификаты,
  sniffing, API статистики, правила маршрутизации (BitTorrent, реклама, приватные IP,
  российские сайты напрямую), DNS-пресеты.
- Агент ноды (`node/agent.py`) забирает конфиг по токену, проверяет `xray -test`,
  перезапускает Xray при изменениях и присылает статистику. Упавший Xray поднимается сам.
- Проверка доступности порта (TCP probe), генерация Reality-ключей (`x25519` через openssl),
  перевыпуск токена.
- Сканер целей REALITY: домен, список домён и диапазон IP / CIDR (или обычные кандидаты,
  если поле пустое). Для каждой цели — TLS-версия, ALPN, обмен ключами, сертификат,
  цепочка, задержка и вердикт «Подходит / Сомнительно / Недоступно»; кнопка «Выбрать»
  подставляет домен в SNI и dest ноды.

**Панель**
- Дашборд: сводка, график трафика за 14 дней, статусы нод, топ по трафику,
  истекающие подписки, журнал событий.
- Аутентификация: PBKDF2-SHA256 (210 000 итераций), сессии в базе, HttpOnly cookie,
  защита от перебора, CSRF-заголовок, предупреждение о пароле по умолчанию.
- Журнал действий администраторов, скачивание SQLite-бэкапа, очистка старых срезов статистики.
- Адаптивная вёрстка (десктоп → планшет → телефон), без сборщиков и node_modules.

**Безопасность**
- 2FA (TOTP) для администратора: QR-код, секрет для ручного ввода, 8 одноразовых
  резервных кодов, отдельный шаг входа с короткоживущим `challenge`.
- API-токены для автоматизации: `dfx_…`, уровни `read` (только GET) и `write`,
  срок действия, отзыв, в базе — только хэш. Заголовок `Authorization: Bearer`.
- Пароли — PBKDF2-SHA256, защита от перебора, журнал событий входа.
- Автовыпуск TLS-сертификатов для TLS-нод (certbot + Let's Encrypt) прямо из
  скрипта установки ноды. Подробности: [docs/SECURITY.md](docs/SECURITY.md).

**Эксплуатация**
- Уведомления в Telegram и/или webhook: нода упала или вернулась, клиент исчерпал
  лимит, вышло обновление. Без повторов — состояние хранится в базе.
  Подробности: [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md).
- Drain ноды: сервер выводится из новых подписок, не разрывая текущие подключения.
- Миграция клиентов между нодами одной кнопкой, с сохранением лимитов и статистики.
- Сортировка подписки по TCP-задержке: ближайшие ноды первыми, недоступные в конце.
  Подробности: [docs/OPERATIONS.md](docs/OPERATIONS.md).
- Нагрузочный тест `tools/loadtest.py` (профили panel/agent/sub) и методика
  проверки на реальных VPS: [docs/LOADTEST.md](docs/LOADTEST.md).

**Обновления**
- Панель сама проверяет новые релизы на GitHub и показывает бейдж «Доступно обновление»
  в шапке и в разделе «Настройки → Обновление».
- Кнопка «Обновить» запускает обновление с прогрессом и логом: код заменяется из архива,
  данные и `.env` не трогаются, контейнер перезапускается. Если панель не может обновить
  себя сама — показывается подсказка `dfxray update`.
- `dfxray update` остаётся безопасным fallback-ом и всегда доступен из CLI.

**Инфраструктура**
- Ноль внешних Python-зависимостей: только стандартная библиотека (`http.server`, `sqlite3`, `zlib`).
- SQLite в WAL-режиме, потокобезопасные соединения, транзакции для трафика.
- Docker Compose: панель + нода, healthcheck, non-root пользователи, один том с данными.
- Самообновление панели в Docker: код монтируется из каталога установки
  (`docker-compose.selfupdate.yml`), поэтому кнопка «Обновить» работает без доступа к Docker.

## Скриншоты

| Дашборд | Пользователи |
| --- | --- |
| ![Дашборд](docs/screenshots/dashboard.png) | ![Пользователи](docs/screenshots/users.png) |

| Карточка клиента | Входящие |
| --- | --- |
| ![Карточка](docs/screenshots/user-drawer.png) | ![Входящие](docs/screenshots/inbounds.png) |

| Сканер целей REALITY | Группы |
| --- | --- |
| ![Сканер](docs/screenshots/scanner.png) | ![Группы](docs/screenshots/groups.png) |

| Исходящие | Маршрутизация |
| --- | --- |
| ![Исходящие](docs/screenshots/outbounds.png) | ![Маршрутизация](docs/screenshots/routing.png) |

| Хосты | Конфиг Xray |
| --- | --- |
| ![Хосты](docs/screenshots/hosts.png) | ![Конфиг](docs/screenshots/xray-config.png) |

| Документация API | Обновление из панели |
| --- | --- |
| ![API](docs/screenshots/api-docs.png) | ![Обновление](docs/screenshots/updates.png) |

| Серверы | Агенты нод |
| --- | --- |
| ![Серверы](docs/screenshots/nodes.png) | ![Агенты](docs/screenshots/node-agents.png) |

| Подключение нового сервера | Палитра команд |
| --- | --- |
| ![Подключение](docs/screenshots/node-connect.png) | ![Палитра](docs/screenshots/palette.png) |

| Вход | Страница подписки |
| --- | --- |
| ![Вход](docs/screenshots/login.png) | ![Подписка](docs/screenshots/subscription-page.png) |

| 2FA | Подключение аутентификатора |
| --- | --- |
| ![2FA](docs/screenshots/security-2fa.png) | ![QR](docs/screenshots/2fa-setup.png) |

| Вход с кодом 2FA | API-токены |
| --- | --- |
| ![Вход 2FA](docs/screenshots/login-2fa.png) | ![Токены](docs/screenshots/api-tokens.png) |

| Уведомления | Миграция клиентов |
| --- | --- |
| ![Уведомления](docs/screenshots/notifications.png) | ![Миграция](docs/screenshots/node-migrate.png) |

| Автонастройка сервера | Список SNI |
| --- | --- |
| ![Пресеты](docs/screenshots/node-presets.png) | ![SNI](docs/screenshots/sni-panel.png) |

| Метрики панели | Команды агенту |
| --- | --- |
| ![Метрики](docs/screenshots/dashboard-metrics.png) | ![Команды](docs/screenshots/nodes-actions.png) |

| Telegram-бот продаж | Разделы панели |
| --- | --- |
| ![Бот](docs/screenshots/settings-bot.png) | ![Разделы](docs/screenshots/settings-services.png) |

Скриншоты сняты с демо-данными (`python -m app seed`).

## Быстрый старт

### Установка на VPS одной командой

Свежий сервер (Ubuntu/Debian, CentOS/Fedora, Alpine), root-доступ и, желательно, домен:

```bash
curl -fsSL https://raw.githubusercontent.com/Dolov07KBR/DF_Xray/main/install.sh | sudo bash
```

Установщик поставит Docker, загрузит панель в `/opt/dfxray`, сгенерирует пароль
администратора, соберёт контейнеры и напечатает адрес, логин и пароль.

Домен и HTTPS (Caddy + Let's Encrypt) плюс нода Xray на том же сервере:

```bash
curl -fsSL https://raw.githubusercontent.com/Dolov07KBR/DF_Xray/main/install.sh \
  | sudo bash -s -- --domain panel.example.com --with-node
```

Флаги: `--with-node`, `--no-node`, `--node-port`, `--admin-password`, `--seed-demo`,
`--port`, `--dir`, `--dry-run`, `--uninstall`. Подробности — [docs/INSTALL.md](docs/INSTALL.md).
После установки доступна команда `dfxray`: `status`, `logs`, `password`, `backup`, `update`.

### Docker Compose (рекомендуется)

```bash
git clone https://github.com/Dolov07KBR/DF_Xray.git
cd DF_Xray

cp .env.example .env
# откройте .env и задайте DFX_ADMIN_PASSWORD и DFX_BASE_URL
docker compose up -d panel
```

Панель: <http://localhost:8000> (или ваш `DFX_BASE_URL`). Логин — из `.env`
(`DFX_ADMIN_USERNAME` / `DFX_ADMIN_PASSWORD`).

Демо-данные для быстрого знакомства:

```bash
docker compose exec panel python -m app seed
# или из .env: DFX_SEED_DEMO=1
```

### Локально без Docker

Нужен только Python 3.9+:

```bash
DFX_DATA_DIR=./data DFX_ADMIN_PASSWORD='сильный-пароль' python3 -m app serve
# http://localhost:8000
```

Полезные команды:

```bash
python -m app serve --port 8080     # запуск
python -m app seed                  # демо-данные
python -m app seed --empty          # только схема
python -m app check                 # состояние базы
python -m app gen-config 1 -o xray.json   # конфиг ноды #1 в файл
python -m app reset-password        # сброс пароля администратора
```

## Первая настройка

1. Войдите под администратором из `DFX_ADMIN_USERNAME` / `DFX_ADMIN_PASSWORD`.
2. **Настройки → Общие**: название панели и **публичный адрес** — он попадает в ссылки подписок
   (`https://panel.example.com`). Если панель за прокси, адрес лучше задать явно.
3. **Настройки → Безопасность**: смените пароль. Панель помнит, что пароль дефолтный,
   и показывает предупреждение, пока вы его не смените.
4. **Ноды → Добавить ноду**: создайте первую ноду и скопируйте её токен.
5. **Пользователи → Новый пользователь**: имя, срок, лимит — панель выдаст UUID,
   токен подписки, QR-код и ссылки для всех нод.

## Автонастройка ноды и выбор SNI

Форма нового сервера начинается с блока **Автонастройка**: сценарий выбирается по
протоколу, остальное панель подставит сама.

| Пресет | Что получится |
| --- | --- |
| Reality · Vision | VLESS + TCP + Reality, порт 443, flow `xtls-rprx-vision` — основной вариант |
| Reality · XHTTP | VLESS + XHTTP + Reality, `path /xh` — когда Vision деградирует на мобильных сетях |
| Reality · gRPC | VLESS + gRPC + Reality, `serviceName dfgrpc` |
| TLS · WebSocket | VLESS + WS + TLS, порт 8443, `path /dfws` — за CDN и nginx |
| TLS · gRPC | VLESS + gRPC + TLS, `serviceName dfgrpc` |
| VMess · TLS + WS | VMess + WS + TLS, `path /dfvm` — для старых клиентов |
| Trojan · TLS | Trojan + TCP + TLS — максимальная совместимость |
| Без шифрования | VLESS + TCP без TLS — только для локальных тестов |

Пресет — это только заполнение полей, после него всё можно поправить руками. Панель
проверяет результат на сервере: несовместимые сочетания (Reality без SNI, Vision-flow
у VMess/Trojan, WebSocket у Reality, `path` у TCP, чужой пресет) возвращают 400 с
объяснением, а не молча сохраняются.

SNI — домен-маскировка для Reality и имя сертификата для TLS. Поле SNI работает как
`datalist`, кнопка **Список** открывает панель под формой:

- 13 встроенных доменов (Microsoft, GitHub, Cloudflare, Apple, Amazon, NVIDIA, Adobe…)
  с пояснением и источником «встроенный»;
- поиск по домену и описанию;
- **Проверить** — TLS-проба выбранных доменов: версия TLS, ALPN, задержка, вердикт
  «Подходит / Сомнительно / Недоступен»;
- **Добавить** — свой домен попадает в настройки панели (`custom_sni`), помечается как
  «свой» и доступен во всех формах; лишний можно удалить корзиной;
- **Выбрать** — подставляет домен в SNI, активная строка подсвечивается.

API: `GET /api/nodes/meta` (пресеты, список SNI, допустимые протоколы),
`GET /api/sni`, `POST /api/sni {"domain": "cdn.example.com"}`,
`DELETE /api/sni/{domain}`, `POST /api/reality/scan` — проверка целей.

## Протоколы и конфиги Xray

Панель генерирует `config.json` под схему Xray 25/26. Что важно знать:

| Что | Значение |
|-----|----------|
| Транспорты | `tcp`, `ws`, `grpc`, `xhttp`, `httpupgrade` (алиасы `raw`, `websocket`, `splithttp` принимаются на вход) |
| Безопасность | `none`, `tls`, `reality`; Reality — только с `tcp` / `grpc` / `xhttp` |
| Reality-сервер | `target`, `xver`, `serverNames`, `privateKey`, `shortIds` (без устаревшего `dest` и клиентского `spiderX`) |
| Vision | `flow: "xtls-rprx-vision"` только для VLESS + TCP + TLS/Reality; на WS/gRPC/XHTTP flow запрещён |
| ALPN | gRPC — `h2`, WS/HTTPUpgrade — `http/1.1`, Reality — без ALPN |
| Статистика | `policy.levels["0"].statsUserUplink/statsUserDownlink`; `stats: {}` остаётся для StatsService |

Сгенерированный конфиг можно проверить до применения:

```bash
xray -test -config /usr/local/etc/xray/config.json    # на ноде
curl -s -X POST $PANEL/api/nodes/1/actions \
     -H 'X-Requested-With: DF_Xray' -H 'Content-Type: application/json' \
     -b cookies.txt -d '{"action":"test_config"}'      # через агент
```

`app/xraycheck.py` прогоняет тот же конфиг по схеме до отправки на ноду:
ловит неизвестные поля, несовместимые сочетания (Reality + WS, flow + WS, gRPC без
`serviceName`), неверные ALPN и shortId. Клиентские ссылки (`vless://`, `vmess://`,
`trojan://`) собираются с теми же параметрами, что и серверная часть, — поэтому
импортируются v2rayNG, NekoBox, Hiddify и Happ без ручной правки.

## Метрики: процессор и память

- Панель: `app/sysinfo.py` снимает CPU, память, LA1, диск, uptime каждые 20 секунд
  и пишет в таблицу `metrics` с `node_id = 0`.
- Ноды: агент присылает `cpu`, `cores`, `memory` в heartbeat; панель пишет ту же серию
  для `node_id` ноды и показывает CPU/RAM в карточке и на дашборде.
- API: `GET /api/metrics?node_id=0&minutes=60` →
  `{series:[{ts,cpu,mem,mem_used,mem_total,load1}], current, host}`,
  `GET /api/dashboard` — блок `system` с тем же содержимым.
- История чистится автоматически (`prune_metrics`), чтобы база не разрасталась.

## Управление Xray из панели

```bash
# поставить команду ноде
curl -s -X POST http://panel:8000/api/nodes/1/actions \
     -H 'X-Requested-With: DF_Xray' -H 'Content-Type: application/json' \
     -b cookies.txt -d '{"action":"restart_xray"}'
# {"ok":true,"id":7,"action":"restart_xray","status":"pending"}

# статус последних команд
curl -s -b cookies.txt http://panel:8000/api/nodes/1/actions
```

Агент забирает очередь в `GET /api/agent/config` (поле `commands`), выполняет и
отчитывается в `POST /api/agent/command {"id":7,"status":"done","result":"..."}`.
Доступны `restart_xray`, `test_config`, `restart_agent`. В интерфейсе — иконки
«перезапустить Xray» и «проверить конфиг» в карточке ноды.

На одиночной установке (`docker compose up`) Xray живёт в контейнере ноды рядом
с панелью, но путь тот же: команда идёт через агент, поэтому кнопка работает и
«локально», и для удалённых серверов без дополнительных настроек.

## Telegram-бот продаж

1. Создайте бота у [@BotFather](https://t.me/BotFather) (`/newbot`) и скопируйте токен.
2. «Настройки → Telegram-бот»: вставьте токен, включите бота, укажите приветствие,
   тарифы (дни, ГБ, цена в ₽ и Stars) и режим оплаты.
3. Нажмите «Проверить токен» — панель вызовет `getMe` и покажет `@username`.
4. Напишите боту `/start` — если чат администратора не задан, первый написавший
   становится администратором (этот chat_id виден в `/stats`).

Режимы оплаты:

- **Telegram Stars** — бот выставляет счёт (`sendInvoice`, валюта `XTR`), после оплаты
  получает `successful_payment` с `payload = order:<id>` и сразу выдаёт доступ.
- **Ручной** — бот показывает реквизиты, заказ попадает в панель («Заказы»), админ
  подтверждает кнопкой или командой `/approve <id>`; `/deny <id>` отклоняет.

После оплаты панель создаёт клиента `tg_<username>` (или продлевает существующего),
добавляет дни и трафик из тарифа и отправляет ссылку `public_base_url + /sub/<token>`.
Пробный доступ выдаётся один раз (`bot_trial_days`, `bot_trial_gb`) и запоминается
в `bot_users.trial_used`. Все ошибки Telegram видны в панели (`bot_last_error`).

API: `GET/PATCH /api/bot`, `POST /api/bot/test`, `POST /api/bot/restart`,
`GET /api/bot/orders`, `POST /api/bot/orders/<id> {"action":"approve"|"deny"}`.

## Как подключить ноду

Панель не ходит на ноды «снаружи»: агент сам опрашивает панель, поэтому нода может жить
за NAT и без открытых портов панели.

1. В панели создайте ноду → **Конфиг** → скопируйте токен и фрагмент `docker-compose`.
2. В `.env` на сервере ноды:

```env
NODE_TOKEN=<токен из панели>
PANEL_INTERNAL_URL=http://panel:8000   # если нода рядом с панелью
```

3. Запустите ноду:

```bash
docker compose up -d node-de
docker compose logs -f node-de
```

Агент раз в 30 секунд:

- забирает `config.json` (`GET /api/agent/config`);
- проверяет его через `xray -test` и применяет только валидный конфиг;
- перезапускает Xray при изменении ревизии конфига;
- снимает счётчики `xray api statsquery -reset` и отправляет их на панель
  (`POST /api/agent/report`), панель обновляет лимиты и статусы;
- шлёт heartbeat, если трафика нет.

Ноду можно запустить и без Docker (например, рядом с системным Xray):

```bash
DFX_PANEL_URL=https://panel.example.com \
DFX_NODE_TOKEN=... \
DFX_CONFIG_PATH=/usr/local/etc/xray/config.json \
python3 node/agent.py
```

Отладка без Xray: `DFX_DRY_RUN=1` — агент напишет конфиг и проверит цикл, но не будет
запускать процесс.

## Подписки и QR-коды

| Адрес | Что отдаёт |
| --- | --- |
| `/sub/<token>` | base64-список ссылок + заголовки профиля |
| `/sub/<token>/plain` | тот же список обычным текстом |
| `/sub/<token>/info` | JSON: расход, лимит, срок, ноды |
| `/sub/<token>/page` | публичная HTML-страница с QR и конфигурациями |
| `/sub/<token>/qr.svg` / `.png` | QR-код подписки |
| `/api/users/<id>/qr.svg?node_id=N` | QR-код конкретной конфигурации (для админа) |

Формат заголовков соответствует распространённой практике (v2rayNG, NekoBox, Streisand,
Hiddify, sing-box):

```
subscription-userinfo: upload=1234; download=5678; total=0; expire=1798588799
profile-title: base64:REZfWHJheQ==
profile-update-interval: 12
profile-web-page-url: https://panel.example.com/sub/<token>/page
```

Если пользователь отключён/просрочен/исчерпал лимит, подписка отдаёт пустой список
и заголовок `x-dfxray-status`, чтобы клиент не получал «битые» конфиги.

## Лимиты и сроки

- `limit_bytes` — суммарный лимит (upload + download). `0` = без лимита.
- `expires_at` — дата окончания. Пусто = бессрочно.
- Статус вычисляется по данным, а не хранится: `active`, `limited`, `expired`, `disabled`.
- В конфиг ноды попадают только пользователи со статусом `active`; при следующем опросе
  агента «лишние» клиенты исчезают из Xray.
- Панель возвращает в ответе на отчёт список `blocked` — агент пишет их в лог.
- После продления или сброса трафика доступ возвращается автоматически.

## Архитектура

```
                        ┌──────────────────────────────┐
      браузер ────────► │  DF_Xray Panel (Python stdlib)│
      (SPA + JSON)      │  http.server · SQLite (WAL)   │
                        │  Xray config generator        │
                        └───────┬───────────────┬──────┘
                                │               │
                    /sub/<token>│               │ /api/agent/config, /report
                                │               │ (pull, по токену ноды)
                                ▼               ▼
                        ┌───────────────┐   ┌──────────────────────────────┐
                        │   Клиенты     │   │ DF_Xray Node (Alpine + Xray) │
                        │ v2rayNG, etc. │   │ agent.py ⇄ xray -test / run  │
                        └───────────────┘   │ config.json, geoip/geosite   │
                                            └──────────────────────────────┘
```

- **Панель** — один процесс, статика + API, SQLite-файл в `/data`.
- **Нода** — контейнер с Xray и агентом; конфиг тянется по HTTPS, токен один на ноду.
- **Трафик** — Xray считает байты по `email` (= username) и `statsquery`, агент отправляет
  дельты, панель пишет их в суточные срезы и суммарные счётчики.
- **Мульти-ноды** — агенты независимы; можно ограничивать пользователя списком нод.

## Настройки и переменные окружения

Панель:

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DFX_DATA_DIR` | `./data` | каталог SQLite и служебных файлов |
| `DFX_HOST` / `DFX_PORT` | `0.0.0.0` / `8000` | адрес панели |
| `DFX_BASE_URL` | авто | публичный адрес для ссылок подписок |
| `DFX_ADMIN_USERNAME` | `admin` | первый администратор |
| `DFX_ADMIN_PASSWORD` | `admin` ⚠️ | пароль первого администратора |
| `DFX_SESSION_TTL_HOURS` | `168` | срок жизни сессии |
| `DFX_TRUST_PROXY` | `1` | доверять `X-Forwarded-*` |
| `DFX_SEED_DEMO` | `0` | демо-данные при первом старте |
| `DFX_NODE_OFFLINE_AFTER` | `180` | секунд без heartbeat до «офлайн» |
| `DFX_AGENT_POLL` | `30` | период опроса нод |

Нода:

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DFX_PANEL_URL` | — | адрес панели (обязательно) |
| `DFX_NODE_TOKEN` | — | токен ноды из панели (обязательно) |
| `DFX_XRAY_BIN` | `/usr/local/bin/xray` | путь к бинарнику |
| `DFX_CONFIG_PATH` | `/etc/xray/config.json` | куда писать конфиг |
| `DFX_STATS_API` | `127.0.0.1:10085` | gRPC API статистики Xray |
| `DFX_POLL` | `30` | период опроса (сек) |
| `DFX_DRY_RUN` | `0` | не запускать Xray |
| `DFX_LOG_LEVEL` | `info` | `debug`, `info`, `warn`, `error` |

Настройки из интерфейса (хранятся в таблице `settings`): название и подзаголовок панели,
публичный адрес, оформление подписки, лимиты по умолчанию, DNS-пресет, правила
маршрутизации, период хранения статистики, подпись в футере.

## Клиентская часть API

Все админские запросы требуют cookie сессии и заголовок `X-Requested-With: DF_Xray`
(кроме `GET`). Ошибки — `{"error": "..."}` с соответствующим HTTP-кодом.

| Метод | Путь | Назначение |
| --- | --- | --- |
| `POST` | `/api/auth/login` | вход, ставит cookie |
| `POST` | `/api/auth/logout` | выход |
| `GET` | `/api/me` | текущий администратор |
| `GET` | `/api/dashboard` | сводка дашборда |
| `GET` | `/api/users` | список (`q`, `status`, `sort`, `limit`, `offset`) |
| `POST` | `/api/users` | создать |
| `GET/PATCH/DELETE` | `/api/users/<id>` | карточка/изменение/удаление |
| `POST` | `/api/users/<id>/action` | `enable`, `disable`, `reset_traffic`, `rotate_uuid`, `rotate_sub`, `extend`, `set_limit` |
| `GET` | `/api/users/export` | CSV |
| `GET` | `/api/nodes` | список нод |
| `POST` | `/api/nodes` | создать ноду |
| `GET/PATCH/DELETE` | `/api/nodes/<id>` | карточка/изменение/удаление |
| `GET` | `/api/nodes/<id>/config` | сгенерированный `config.json` |
| `POST` | `/api/nodes/<id>/probe` | TCP-проверка |
| `POST` | `/api/nodes/<id>/reality-keys` | новые x25519-ключи |
| `GET` | `/api/nodes/<id>/connect` | команда установки сервера (systemd / Docker) |
| `POST` | `/api/nodes/<id>/install-token` | перевыпустить ссылку установки |
| `GET` | `/api/node/install/<install_token>.sh` | bash-скрипт установки ноды (публичный) |
| `GET` | `/api/node/agent.py` | исходник агента для установки (публичный) |
| `GET` | `/api/subscriptions` | подписки и их настройки |
| `GET/PATCH` | `/api/settings` | настройки панели |
| `GET` | `/api/audit` | журнал |
| `GET` | `/api/maintenance/backup` | скачать SQLite-базу |
| `POST` | `/api/maintenance/purge-traffic` | очистить старые срезы |
| `GET/POST` | `/api/agent/*` | конфиг, heartbeat с метриками и статистика (токен в `X-Node-Token`) |

## Безопасность

- Пароли — PBKDF2-SHA256, 210 000 итераций, случайная соль; сравнение через `compare_digest`.
- Сессии хранятся в базе в виде SHA-256-хешей, cookie `HttpOnly` + `SameSite=Lax`,
  `Secure` при HTTPS, срок 7 дней (настраивается).
- Не более 8 попыток входа за 5 минут с одного IP.
- Мутации по API требуют заголовок `X-Requested-With` (CSRF-барьер для cookie-аутентификации).
- 2FA (TOTP) по RFC 6238 с одноразовыми резервными кодами; включение и выключение
  завершают все сессии. См. [docs/SECURITY.md](docs/SECURITY.md).
- API-токены: `read` (только GET/HEAD) и `write`, в базе хранится SHA-256 хэш,
  значение показывается один раз; Bearer-запросы не требуют CSRF-заголовка.
- CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Robots-Tag: noindex`.
- Токены нод и ссылки подписок — секреты: не публикуйте их, перевыпускайте при утечке.
- Поставьте панель за HTTPS-прокси (Caddy/nginx/Traefik). Пример Caddy:

```caddy
panel.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

- Обязательно смените пароль из `.env` и не оставляйте `admin/admin` в интернете.

## Бэкапы и обслуживание

- `Настройки → Обслуживание → Скачать бэкап` — консистентная копия SQLite (через backup API).
- Или копируйте каталог `./data` (в нём `panel.db`, `panel.db-wal`). Для горячего бэкапа
  лучше использовать встроенную кнопку или `sqlite3 panel.db ".backup backup.db"`.
- Старые срезы трафика удаляются по кнопке «Очистить старую статистику» с учётом
  периода хранения (по умолчанию 90 дней); суммарные счётчики пользователей сохраняются.
- Восстановление: остановите панель, положите файл как `data/panel.db`, запустите снова.

## Разработка и тесты

```bash
python3 -m unittest discover -s tests -v
```

95 тестов: юнит-тесты ссылок/конфигов/QR/паролей/TOTP/латентности, проверка
сгенерированных конфигов по схеме Xray (`tests/test_protocols.py`) и интеграционные —
живой HTTP-сервер, вход, 2FA (challenge, резервные коды), API-токены и scope,
уведомления, drain и миграция клиентов, создание пользователя, подписка, QR, лимиты
через отчёт агента, бэкап, команды нодам, метрики и Telegram-бот.

Нагрузочный тест (отдельно, без зависимостей):

```bash
python3 tools/loadtest.py --profile panel --password 'panel-demo-2026' --workers 16 --duration 10
```

Структура разработки:

```bash
python3 -m app serve --port 8000   # локальный запуск без Docker
```

Внешних зависимостей нет: `pip install` не нужен ни для запуска, ни для тестов.
Фронтенд — нативные ES-модули без сборки.

## Структура проекта

```
.
├── app/                    # бэкенд панели (stdlib)
│   ├── api.py              # JSON API + агентские эндпоинты
│   ├── pages.py            # SPA-оболочка и публичная страница подписки
│   ├── server.py           # HTTP-сервер, роутер, статика, cookie
│   ├── db.py               # схема SQLite, настройки, миграции
│   ├── repo.py             # пользователи, ноды, трафик, журнал
│   ├── xray.py             # генерация config.json и клиентских ссылок
│   ├── xraycheck.py        # валидатор конфига Xray (схема 25/26)
│   ├── sysinfo.py          # CPU/RAM/uptime панели и сэмплер метрик
│   ├── tgbot.py            # Telegram-бот продаж (long polling, заказы, Stars)
│   ├── reality.py          # сканер целей REALITY (TLS, ALPN, сертификаты)
│   ├── nodeinstall.py      # скрипт установки ноды и команды подключения
│   ├── updates.py          # проверка релизов и самообновление панели
│   ├── qr.py               # SVG/PNG QR-коды
│   ├── auth.py             # пароли, сессии, 2FA и API-токены
│   ├── totp.py             # TOTP (RFC 6238) и резервные коды
│   ├── notify.py           # Telegram/webhook и проверка событий
│   ├── latency.py          # замер задержки до нод и сортировка ссылок
│   ├── seed.py             # демо-данные
│   └── vendor/qrcode/      # вендорный энкодер (BSD-3, см. LICENSE рядом)
├── static/                 # SPA: CSS, ES-модули, иконки
├── node/                   # агент ноды + Dockerfile с Xray
├── tests/                  # unittest (юнит + интеграционные)
├── tools/loadtest.py       # нагрузочный тест (stdlib)
├── docs/screenshots/       # скриншоты интерфейса
├── docs/MULTISERVER.md     # подключение и обслуживание нескольких нод
├── docs/SECURITY.md        # 2FA, API-токены, TLS
├── docs/NOTIFICATIONS.md   # Telegram, webhook, события
├── docs/OPERATIONS.md      # drain, миграция клиентов, латентность
├── docs/LOADTEST.md        # нагрузочные профили и результаты
├── CHANGELOG.md            # история версий
├── Dockerfile              # образ панели
├── docker-compose.yml      # панель + нода
├── docker-compose.selfupdate.yml  # монтирует код для кнопки «Обновить»
├── .env.example
└── LICENSE                 # GPL-3.0-only
```

## Дорожная карта

- [ ] Резервные копии по расписанию и экспорт/импорт пользователей JSON.
- [ ] Несколько администраторов с ролями (админ/оператор).
- [ ] Xray API горячего применения конфигурации без перезапуска.
- [ ] Уведомления по расписанию: сводка раз в сутки и напоминания об окончании подписки.
- [ ] Полноценный sing-box/Clash-профиль в подписке (`/sub/<token>?format=clash`).
- [ ] WebAuthn/аппаратные ключи как второй фактор рядом с TOTP.
- [ ] Postgres как альтернатива SQLite для больших инсталляций.

## Лицензия

DF_Xray Panel распространяется под **GNU General Public License v3.0 (GPL-3.0-only)** —
см. [LICENSE](LICENSE). Вендорный QR-энкодер `app/vendor/qrcode` — BSD-3-Clause
(см. `app/vendor/qrcode/LICENSE`).

Xray-core — отдельный проект под MPL-2.0; панель только генерирует его конфигурацию.
