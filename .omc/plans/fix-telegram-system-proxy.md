# План исправления подключения Telegram через системный прокси Windows

Статус: **ожидает утверждения владельца**. План не разрешает реализацию сам по себе.

## 1. Цель и подтверждённая причина

Цель: `uv run tld start` должен подключать существующую Telethon-сессию и выполнять `get_me`, когда доступ к Telegram на Windows идёт через включённый системный прокси, при этом прямое подключение должно продолжить работать на компьютерах без прокси.

Подтверждённая причина текущего сбоя:

- `TelethonTelegramGateway.connect()` создаёт `ControlledTelegramClient` без `proxy` и сразу вызывает `connect()` (`src/telegram_lead_discovery/collector/adapter/telethon_gateway.py:80-87`).
- В окружении закреплён только `telethon==1.44.0`; `python-socks` отсутствует (`pyproject.toml:19`). Telethon 1.44 предупреждает и игнорирует `proxy`, если `python-socks` не установлен.
- На рабочем компьютере прямой TCP к Telegram не проходит, а системный HTTP CONNECT-прокси проводит соединение к сохранённому Telegram DC.
- После ошибки первого подключения `RuntimeCoordinator` удаляет gateway и запускает только нетелеграмные циклы (`src/telegram_lead_discovery/infrastructure/runtime.py:261-281`), поэтому требуемое COL-020 переподключение без перезапуска фактически невозможно.

## 2. Требования к результату

1. Режим подключения — обычная настройка `telegram.proxy_mode` со значениями `auto|direct`; значение по умолчанию — `auto`.
2. `auto` на Windows использует включённый статический прокси текущего пользователя. Если прокси выключен или отсутствует, используется прямое подключение.
3. Порядок выбора записи системного прокси: `https` → `http` → `socks` → единая запись без префикса. Единая запись без схемы трактуется как HTTP CONNECT; `socks` — как SOCKS5.
4. Допустимые протоколы: `http`, `socks5`, `socks4`; обязательны непустой адрес и порт `1..65535`. Для SOCKS используется `rdns=true`.
5. PAC/WPAD не реализуются в этом изменении. Если статического прокси нет, `auto` использует прямой путь; неподдерживаемая или повреждённая статическая запись даёт безопасный код `telegram_proxy_invalid`, а не молчаливый прямой обход.
6. Полное значение `ProxyServer`, адрес, имя пользователя и пароль не сохраняются в SQLite, revisions, журналах, метриках, HTML, экспортах и диагностических файлах. В журнал допустимы только `route=system_proxy|direct`, `proxy_type=http|socks5|socks4` и безопасный код результата.
7. Конфигурация прокси передаётся в Telethon только внутри реализации `TelegramGateway`; Telethon-типы не выходят за границу COL (D-006, COL-001).
8. После временной ошибки подключения runtime сохраняет единственного владельца gateway и повторяет подключение по COL-020: `1, 5, 30, 120`, затем каждые `300` секунд. После успеха Telegram-циклы запускаются ровно один раз.
9. Исправление не запускает keyword/global search и не меняет правила graph discovery, FloodWait, Zero Stars или единственного владельца session.

## 3. Нормативные изменения до кода

1. `docs/prd/DECISION_LOG.md`
   - Добавить `D-078`: Windows runtime поддерживает `telegram.proxy_mode=auto|direct`; `auto` использует статический WinINET proxy текущего пользователя, иначе direct; proxy material остаётся только в памяти; reconnect следует COL-020.
2. `docs/prd/shared/INTEGRATION_CONTRACTS.md`
   - Добавить нейтральный `TelegramConnectionConfig`/`TelegramProxyConfig` без Telethon-типов.
   - Зафиксировать безопасные ошибки `telegram_proxy_invalid`, `telegram_proxy_dependency_missing`, `telegram_proxy_unavailable`, `telegram_direct_unavailable` и поведение runtime.
3. `docs/prd/shared/DOMAIN_MODEL.md`
   - Добавить обычную настройку `telegram.proxy_mode: auto|direct`, default `auto`; значения прокси в доменную модель не добавлять.
4. `docs/prd/modules/02-telegram-collector/PRD.md`
   - Добавить `COL-031` и `AT-COL-031`: gateway применяет переданную proxy-конфигурацию, выполняет `connect()+get_me`, сохраняет direct path без прокси и не создаёт второго владельца session.
   - Уточнить COL-020: стартовая ошибка тоже входит в бесконечный reconnect, успешное восстановление запускает Telegram-циклы один раз.
5. `docs/prd/modules/09-operator-settings/PRD.md`
   - Добавить `SET-016` и `AT-SET-016`: типизированная настройка `telegram.proxy_mode`, default `auto`, валидация только `auto|direct`, изменение через CSRF/optimistic version.
   - Уточнить SET-013: проверка Telegram показывает route и безопасный result code, не меняя настройки.
6. `docs/prd/modules/11-security/PRD.md`
   - Добавить `SEC-019` и `AT-SEC-019`: системная proxy-конфигурация только в памяти; credentials и raw registry value запрещены во всех выходах; redaction покрывает ключи `proxy`, `proxy_url`, `proxy_server`, `username`, `password`.
7. `docs/prd/modules/12-deployment-infrastructure/PRD.md`
   - Добавить `INF-024` и `AT-INF-024`: чтение WinINET текущего пользователя, детерминированный разбор, dependency lock и передача нейтральной конфигурации в gateway.
8. `docs/prd/modules/10-administration-observability/PRD.md`
   - Добавить `OBS-023` и `AT-OBS-023`: отдельные безопасные reason codes direct/proxy/config/dependency и переход `blocked/degraded → healthy` после reconnect.
9. `docs/prd/TRACEABILITY.md`
   - Расширить диапазоны до `COL-031`, `SET-016`, `SEC-019`, `INF-024`, `OBS-023`; добавить путь проверки proxy connect/reconnect и отсутствие утечки.
   - Запустить проверку уникальности ID, существования ссылок и соответствия requirement ↔ acceptance test.

## 4. Реализация

### 4.1. Зависимость прокси

Файлы: `pyproject.toml`, `uv.lock`, `tests/unit/test_infrastructure.py`.

- Добавить закреплённую runtime-зависимость `python-socks[asyncio]==2.8.2` и обновить lock через `uv`.
- Не использовать новый основной выпуск `3.x` без отдельной проверки совместимости: Telethon 1.44 использует внутренние классы ошибок `python_socks`.
- Расширить dependency-тест: Telethon и `python-socks[asyncio]` присутствуют в проекте и `uv sync --frozen` не меняет lock.

### 4.2. Нейтральный разбор системного прокси

Новый файл: `src/telegram_lead_discovery/infrastructure/windows_proxy.py`.

- Ввести immutable dataclass `TelegramProxyConfig(proxy_type, host, port, username, password, rdns)` и исключение с закрытым `reason_code`.
- Реализовать `resolve_telegram_proxy(mode, registry_reader=...)`; зависимость чтения реестра должна внедряться для unit-тестов.
- Читать только `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings`: `ProxyEnable`, `ProxyServer`, `AutoConfigURL`.
- Реализовать точный порядок и валидацию из раздела 2. Не возвращать и не журналировать raw registry value.
- На не-Windows: `auto` возвращает direct, `direct` всегда возвращает direct.

### 4.3. Настройка и интерфейс оператора

Файлы: `src/telegram_lead_discovery/settings/defaults.py`, `settings/service.py`, `dashboard/routes/settings.py`, `dashboard/templates/settings.html`, `tests/unit/test_security_settings.py`, `tests/integration/test_storage_settings.py`.

- Добавить `telegram.proxy_mode=(string, auto)` в `DEFAULT_SETTINGS`; существующие базы получают значение через идемпотентный `seed_defaults`, без новой таблицы и без изменения схемы.
- В `_validate` принимать только `auto|direct`.
- Заменить произвольное текстовое редактирование этой настройки на select `Автоматически (системный прокси)` / `Прямое подключение`.
- Добавить защищённое POST-действие проверки Telegram session из SET-013. Ответ содержит только: выбранный route, `ok|failed`, безопасный reason code; проверка не создаёт SettingChange и не открывает вторую session, если runtime уже владеет ею.

### 4.4. Передача конфигурации в Telethon

Файлы: `src/telegram_lead_discovery/collector/adapter/telethon_gateway.py`, `collector/adapter/controlled_client.py`, новый/существующий adapter test.

- Расширить конструктор `TelethonTelegramGateway` аргументом `connection_config`; fake gateway и shared protocol менять не требуется, так как это wiring adapter-а, а не новый Telegram operation.
- Преобразовать `TelegramProxyConfig` в документированный Telethon dict: `proxy_type`, `addr`, `port`, `username`, `password`, `rdns`; передать его в `ControlledTelegramClient(..., proxy=...)`.
- Перед созданием клиента при выбранном прокси явно проверить импорт `python_socks`; отсутствие dependency должно давать `telegram_proxy_dependency_missing`, а не warning с молчаливым игнорированием.
- Сохранить существующий session path, `api_id/api_hash`, `connect()` и `get_me`; не менять graph `_call`, request locks, FloodWait и 30-секундный graph deadline.
- Маппить ошибки так, чтобы runtime различал invalid config, недоступный прокси и недоступный direct route, не раскрывая endpoint.

### 4.5. Runtime и переподключение

Файл: `src/telegram_lead_discovery/infrastructure/runtime.py`.

- После `seed_defaults` получить `telegram.proxy_mode`, разрешить системный route и передать `connection_config` в `RuntimeCoordinator`/gateway.
- При первой ошибке не присваивать `gateway=None`. Запустить один supervised connection loop с задержками COL-020.
- До успешного `connect()+get_me`: collector/discovery `blocked` или `degraded` с точным safe reason; нет Telegram jobs/calls.
- После успеха атомарно запустить keyword, graph, collector, live и reconciliation loops ровно один раз; обновить `app.state.gateway` и health.
- Shutdown должен остановить reconnect loop до `gateway.disconnect()` и не оставлять фоновых попыток.

### 4.6. Защита и наблюдаемость

Файлы: `src/telegram_lead_discovery/security/redaction.py`, `security/preflight.py`, `observability/*`, соответствующие тесты.

- Добавить proxy-sensitive keys в redaction и тестовые canary-значения.
- Preflight проверяет только валидность режима/системной записи и наличие dependency; он не открывает Telegram-соединение.
- Добавить события `telegram_gateway.connecting`, `.connected`, `.connect_failed`, `.reconnect_scheduled` с безопасными полями `route`, `proxy_type`, `reason_code`, `attempt`, `delay_seconds`.
- Не писать host, port, registry value, credentials, DC IP, session path и exception text.

## 5. Автоматические проверки

1. Unit resolver:
   - proxy disabled/empty → direct;
   - simple `host:port` → HTTP;
   - protocol map выбирает `https`, затем `http`, затем `socks`;
   - SOCKS получает `rdns=true`;
   - invalid scheme/host/port → `telegram_proxy_invalid`;
   - `direct` не читает реестр;
   - raw proxy/credentials отсутствуют в логах и результатах redaction.
2. Adapter:
   - monkeypatch `ControlledTelegramClient` и доказать точный `proxy` dict;
   - direct передаёт `proxy=None`;
   - выбранный proxy без `python_socks` завершается безопасной ошибкой до network call;
   - `connect()+get_me` возвращает AccountSnapshot;
   - существующие graph-control tests проходят без изменений семантики.
3. Runtime:
   - первая connect-ошибка запускает задержки `1/5/30/120/300` и не удаляет gateway;
   - успешный reconnect запускает каждый Telegram-loop ровно один раз;
   - shutdown останавливает reconnect;
   - invalid proxy блокирует Telegram, но UI и нетелеграмные циклы остаются доступны.
4. Settings/UI:
   - default `auto`, допустимы только `auto|direct`;
   - изменение создаёт одну revision и увеличивает settings version;
   - session check не создаёт revision и не запускает второго session owner;
   - HTML/API не содержат raw proxy.
5. Команды проверки:
   - `uv sync --frozen`;
   - `uv run ruff check src tests`;
   - целевые `pytest` для settings, security, infrastructure, runtime и Telethon adapter;
   - полный `uv run pytest -q`; известные/чужие падения отделить от регрессий изменения, не объявлять общий PASS при любом падении.

## 6. Живая приёмка на рабочем компьютере

1. Зафиксировать, что `telegram.proxy_mode=auto`, Windows proxy включён, а прямой Telegram DC недоступен. Значение proxy в отчёт не писать.
2. Выполнить `uv run tld migrate`, затем `uv run tld start`.
3. Подтвердить фактический `connect()+get_me`: Telegram account ID совпал с ожидаемым; health `collector` и `discovery` стали `healthy`; в журнале route=`system_proxy`, без адреса/учётных данных.
4. Остановить локальный proxy, подтвердить безопасное состояние и reconnect schedule; вернуть proxy и подтвердить восстановление без рестарта и без дублирования loops.
5. Выполнить исходный graph-only обход по десяти уникальным сидам владельца. Перед запуском проверить отсутствие active keyword run; после запуска доказать по БД, что создан только `run_type=graph`/`job_type=discovery`, а `search_global` и keyword job не выполнялись.
6. Дождаться terminal graph state, проверить сохранённые `SourceDiscoveryEvent` и `GraphDiscoveryPost`, сформировать отдельный UTF-8 `.txt` с seeds, skipped refs, counters, найденными смежными источниками и ссылками.

Исправление считается рабочим только после шагов 3 и 5–6. Успешные unit-тесты, открывшийся `/health` или один TCP CONNECT без `get_me` не закрывают задачу.

## 7. Риски и меры

- **Неподдерживаемый PAC/WPAD.** Не пытаться вычислять PAC внутри приложения; показывать безопасный код, использовать direct только при отсутствии статической записи. PAC остаётся вне этого изменения.
- **Молчаливое игнорирование proxy Telethon.** Явная проверка `python_socks` до создания клиента и закреплённая dependency.
- **Утечка proxy credentials.** Neutral DTO только в памяти, расширенный redaction, canary scan SQLite/logs/HTML/exports.
- **Двойная Telethon session.** Session check переиспользует runtime gateway либо отклоняется как `telegram_session_busy`; reconnect loop единственный.
- **Дублирование Telegram workers после reconnect.** Идемпотентный `_start_telegram_loops_once` и интеграционный тест по identity task-ов.
- **Регрессия graph request control.** Не менять `ControlledTelegramClient._call`; обязательно прогнать `test_telethon_graph_request_control.py` и `test_graph_call_deadline.py`.
- **Скрытый переход к direct при повреждённом proxy.** Повреждённая включённая запись блокирует подключение с `telegram_proxy_invalid`; direct fallback только когда proxy действительно выключен/отсутствует.

## 8. Граница выполнения

Этот документ — план для LLM-разработчика. До отдельной явной команды владельца запрещены изменения PRD, кода, зависимостей, базы и runtime. После реализации нельзя автоматически запускать глобальный поиск; живая проверка ограничена graph-only сценарием из раздела 6.
