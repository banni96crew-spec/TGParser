# PRD 11 — Security

## 1. Назначение и границы

Модуль определяет обязательные технические средства защиты локального приложения: границу loopback, управление секретами и Telegram session, права файлов, redaction, CSRF-защиту и безопасные процедуры backup/restore.

## 2. Goals и non-goals

### Goals

- Не допустить раскрытия Telegram credentials, bot token и session contents.
- Ограничить web UI локальным компьютером.
- Обеспечить одинаковые security-инварианты во всех 12 модулях.
- Обнаруживать небезопасные права файлов до запуска collector.

### Non-goals

- Remote access, облачная identity-система и multi-user authorization.
- Хранение секретов в SQLite.
- Включение Telegram session-файла в backup или экспорт.

## 3. Принятые решения

- Web UI bind: только `127.0.0.1:8765`, без формы входа.
- Telegram credentials и bot token поступают из environment либо защищённых локальных файлов; environment имеет приоритет.
- Telethon session хранится отдельным файлом в `%LOCALAPPDATA%\TelegramLeadDiscovery\secrets\`.
- Каталоги `secrets`, `data`, `backups` и `logs` создаются под профилем текущего Windows-пользователя.
- ACL для `secrets` разрешает доступ только текущему пользователю и `SYSTEM`; наследование отключено.
- Session-файл не включается в backup, export, logs и диагностические bundles.
- Все HTTP POST используют same-origin, CSRF token и `SameSite=Strict` cookie.
- Секреты маскируются до форматирования log event.

## 4. Functional requirements

| ID | Требование |
|---|---|
| SEC-001 | Startup MUST завершиться до открытия web listener, если его bind-адрес отличается от `127.0.0.1`. |
| SEC-002 | Collector MUST оставаться остановленным, если отсутствуют `TG_API_ID`, `TG_API_HASH` или Telethon session. |
| SEC-003 | Notifications MUST оставаться отключёнными, если отсутствуют `TG_BOT_TOKEN` или `TG_NOTIFY_CHAT_ID`; остальные модули продолжают работать. |
| SEC-004 | SQLite MUST не содержать credentials, bot token или serialized session. |
| SEC-005 | Session MUST храниться только в `%LOCALAPPDATA%\TelegramLeadDiscovery\secrets\telegram.session`. |
| SEC-006 | Startup MUST проверить ACL каталога `secrets`; лишние principals переводят collector в `security_blocked`. |
| SEC-007 | Backup и export MUST исключать каталог `secrets`, environment dump и session-файл. |
| SEC-008 | Redaction MUST обрабатывать значения секретов, ключи `api_hash`, `bot_token`, `authorization`, `session` и URI credentials до записи log. |
| SEC-009 | UI MUST не отображать абсолютные пути за пределами application data directory и MUST не возвращать secret values. |
| SEC-010 | Все изменяющие HTTP endpoints MUST принимать только POST, проверять Origin/Host, CSRF token и content type. |
| SEC-011 | Response headers MUST включать `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` и `Cache-Control: no-store` для страниц конфигурации. |
| SEC-012 | Jinja2 autoescape MUST быть включён; unsafe HTML rendering и inline event handlers запрещены. |
| SEC-013 | Application errors MUST возвращать безопасный публичный код и correlation ID без stack trace в UI. |
| SEC-014 | Diagnostic export MUST проходить redaction scan; найденный secret pattern блокирует создание файла. |
| SEC-015 | Restore MUST выполняться при остановленном приложении и MUST не изменять содержимое `secrets`. |

## 5. Acceptance criteria

| ID | Проверяемый результат |
|---|---|
| AT-SEC-001 | Попытка запуска с `0.0.0.0`, LAN IP или IPv6 wildcard завершается до открытия listener. |
| AT-SEC-002 | При отсутствии Telegram credentials collector имеет `security_blocked`, а UI показывает только имена отсутствующих переменных. |
| AT-SEC-003 | Без notification secrets уведомления отключены, а collector, processing и dashboard продолжают работать. |
| AT-SEC-004 | Полный скан SQLite не находит тестовые credentials, bot token или serialized session. |
| AT-SEC-005 | Telethon создаёт и читает session только по утверждённому пути внутри `secrets`. |
| AT-SEC-006 | Добавление лишнего Windows principal к `secrets` блокирует collector; восстановление ACL возвращает готовность после повторной проверки. |
| AT-SEC-007 | Скан backup и export не находит environment dump, session-файл или содержимое `secrets`. |
| AT-SEC-008 | Все утверждённые secret keys, URI credentials и реальные тестовые значения маскируются до записи log. |
| AT-SEC-009 | API и UI не возвращают secret values и не раскрывают абсолютные пути вне application data directory. |
| AT-SEC-010 | POST без CSRF token, с чужим Origin/Host или неверным content type отклоняется без изменения состояния. |
| AT-SEC-011 | Все утверждённые security headers присутствуют в HTTP responses соответствующих страниц. |
| AT-SEC-012 | Тестовая HTML/JS-строка отображается как текст и не выполняется; inline event handler заблокирован. |
| AT-SEC-013 | Ошибка приложения показывает correlation ID, но не stack trace и не локальный абсолютный путь. |
| AT-SEC-014 | Diagnostic export с тестовым secret pattern блокируется до создания итогового файла. |
| AT-SEC-015 | Restore заменяет SQLite data, но оставляет исходный каталог `secrets` и session-файл byte-identical. |

## 6. Входные и выходные контракты

### Входы

- Environment и пути штатных secret files.
- `SecurityPreflightCommand` при startup и перед collector start.
- HTTP request metadata для same-origin/CSRF-проверки.
- Structured event до записи в log.

### Выходы

- `SecurityPreflightResult(status, checks, safe_errors)`.
- `SecretPresenceSnapshot` без значений.
- Redacted structured event.
- Health component `security`.

## 7. Data ownership

Модуль владеет техническими правилами доступа и вычисляемыми результатами проверок. Он не сохраняет секретные значения в доменной БД. Telethon session принадлежит TelegramGateway и физически хранится в утверждённом secret path.

## 8. Состояния и переходы

Security preflight: `unchecked → passed` либо `unchecked → blocked`; изменение environment/ACL требует повторной проверки `blocked → passed`. Collector запускается только при `passed`.

Secret presence: `missing ↔ configured`; значения никогда не включаются в состояние UI.

## 9. Ошибки, retries и recovery

- Ошибки bind address, ACL и отсутствующей session не исправляются автоматически.
- После ручного исправления оператор запускает preflight повторно.
- Ошибка notification secrets отключает только notifications.
- Ошибка redaction scan блокирует diagnostic export и создаёт безопасный security event.

## 10. Security requirements

Требования SEC-001—SEC-015 обязательны для всех runtime-модулей. Любой новый adapter, export или log sink обязан использовать централизованные secret provider и redactor; собственное чтение secret files модулем запрещено.

## 11. Observability

- Метрики: `security_preflight_total{result}`, `csrf_rejection_total{reason}`, `redaction_match_total{kind}`, `diagnostic_export_block_total`.
- Логи содержат только название проверки, безопасный код результата и correlation ID.
- `security=blocked` делает collector not-ready; ошибка только notification secrets не делает основное приложение not-ready.

## 12. Dependencies

- Upstream: Deployment для Windows paths/process configuration.
- Downstream: все модули; особенно Settings, Collector, Storage, Dashboard, Notifications, Observability.

## 13. MVP и исключённые функции

### MVP

- Loopback boundary, secret provider, session isolation, ACL preflight, redaction, CSRF и безопасные exports.

### DEFERRED

- Подпись diagnostic bundles локальным ключом.

### Исключено

- Remote access, multi-user authorization и включение session-файла в backup.

## 14. Acceptance test catalogue

- `SEC-BOUNDARY`: AT-SEC-001, AT-SEC-010, AT-SEC-011, AT-SEC-012.
- `SEC-SECRETS`: AT-SEC-002, AT-SEC-003, AT-SEC-004, AT-SEC-005, AT-SEC-006, AT-SEC-007, AT-SEC-008.
- `SEC-OUTPUT`: AT-SEC-009, AT-SEC-013, AT-SEC-014.
- `SEC-RESTORE`: AT-SEC-015.

## 15. Decision log references

- DEC-006: secrets outside SQLite.
- DEC-007: loopback UI without login.
- DEC-016: Telethon session isolation and ACL preflight.
- DEC-020: session excluded from backup.
