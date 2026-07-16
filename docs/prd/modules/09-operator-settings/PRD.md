# PRD 09 — Operator Settings and Local Access

## 1. Назначение и границы

Модуль хранит и проверяет рабочие настройки единственного оператора, предоставляет локальные страницы конфигурации и публикует версионированные снимки настроек другим модулям.

Модуль не реализует регистрацию, форму входа, роли, команды, организации и удалённый доступ.

## 2. Goals и non-goals

### Goals

- Дать одному оператору понятный RU-first интерфейс настройки системы.
- Хранить обычные настройки в SQLite с полной историей изменений.
- Хранить секреты только в переменных окружения или защищённых локальных файлах.
- Не допускать запуска зависимого действия с некорректной конфигурацией.

### Non-goals

- Multi-user, RBAC, SSO и управление организациями.
- Передача интерфейса во внешнюю сеть.
- Хранение Telegram API credentials, bot token или session-файла в SQLite.
- Редактирование секретов через web UI.

## 3. Принятые решения

- Оператор ровно один; отдельная сущность пользовательского аккаунта не создаётся.
- Web UI слушает только `127.0.0.1:8765`; форма входа отсутствует.
- Backend: FastAPI + Uvicorn. UI: Jinja2 + HTMX + обычный CSS.
- Обычные настройки хранятся в SQLite.
- Секреты читаются из environment или защищённых файлов; environment имеет приоритет.
- Изменение обычной настройки создаёт immutable revision.
- Интерфейс и пользовательские сообщения — на русском языке.
- Все даты в базе хранятся в UTC; UI отображает их в `Europe/Moscow`.

## 4. Functional requirements

| ID | Требование |
|---|---|
| SET-001 | Система MUST обслуживать web UI только на `127.0.0.1:8765`. |
| SET-002 | Система MUST предоставлять страницы настроек без регистрации и формы входа. |
| SET-003 | Система MUST хранить обычные настройки как типизированные записи `OperatorSetting` и immutable `SettingChange`. |
| SET-004 | Система MUST проверять значение до записи и возвращать понятную ошибку без изменения активной конфигурации. |
| SET-005 | Успешное изменение MUST атомарно записать новую revision, обновить активное значение и увеличить `settings_version`. |
| SET-006 | Система MUST поддерживать группы `telegram`, `discovery`, `collector`, `rules`, `scoring`, `notifications`, `storage`, `observability` и `ui`. |
| SET-007 | Web UI MUST показывать наличие секрета только как `настроен/не настроен`, не раскрывая значение. |
| SET-008 | Секреты MUST читаться из environment; при отсутствии переменной допускается защищённый файл, указанный штатным путём конфигурации. |
| SET-009 | Для Telegram credentials MUST использоваться `TG_API_ID`, `TG_API_HASH`; для уведомлений — `TG_BOT_TOKEN` и `TG_NOTIFY_CHAT_ID`. |
| SET-010 | Изменение настройки MUST публиковать `settings.changed.v1` после commit. |
| SET-011 | Снимок конфигурации MUST содержать `settings_version`; фоновые jobs сохраняют использованную версию. |
| SET-012 | Экспорт настроек MUST исключать секреты, пути к session-файлам и любые masked placeholders. |
| SET-013 | UI MUST предоставлять действие проверки Telegram session и отдельное действие проверки канала уведомлений без сохранения новых значений. |
| SET-014 | Удаление обычной настройки MUST возвращать утверждённое default-значение и создавать revision с причиной `reset_to_default`. |
| SET-015 | Каждое изменение MUST фиксировать UTC-время, ключ, старое и новое несекретное значение и источник `local_ui` или `system`. |

## 5. Acceptance criteria

| ID | Проверяемый результат |
|---|---|
| AT-SET-001 | Соединение с `127.0.0.1:8765` открывает UI; приложение не создаёт listener на `0.0.0.0`, IPv6 wildcard или LAN-адресе. |
| AT-SET-002 | Страницы настроек открываются локально без регистрации и формы входа. |
| AT-SET-003 | После restart типизированные `OperatorSetting` и immutable `SettingChange` восстанавливаются из SQLite. |
| AT-SET-004 | Некорректный интервал reconciliation отклоняется, а значение и `settings_version` остаются прежними. |
| AT-SET-005 | Успешное изменение создаёт ровно одну revision, обновляет active value и увеличивает `settings_version` в одной транзакции. |
| AT-SET-006 | Settings snapshot содержит все девять утверждённых групп конфигурации. |
| AT-SET-007 | API и HTML показывают только `настроен/не настроен` и не содержат secret values. |
| AT-SET-008 | При одновременном наличии environment и защищённого файла используется environment; при его отсутствии читается файл. |
| AT-SET-009 | Telegram и notification checks используют только утверждённые имена environment variables и сообщают отсутствующие имена без значений. |
| AT-SET-010 | Успешный commit создаёт ровно одно событие `settings.changed.v1`; откат транзакции не создаёт событие. |
| AT-SET-011 | Новый persisted job сохраняет точную `settings_version` использованного snapshot. |
| AT-SET-012 | Экспорт настроек не содержит секретов, session paths и masked placeholders и повторно импортируется как набор обычных настроек. |
| AT-SET-013 | Проверки Telegram session и notification channel возвращают результат без изменения настроек и revisions. |
| AT-SET-014 | Reset возвращает default, увеличивает версию и создаёт revision с причиной `reset_to_default`. |
| AT-SET-015 | Revision содержит UTC-время, key, старое и новое несекретное значение и допустимый source. |

## 6. Входные и выходные контракты

### Входы

- `UpdateSettingCommand(key, typed_value, expected_settings_version)`.
- `ResetSettingCommand(key, expected_settings_version)`.
- `ValidateRuntimeDependencyCommand(dependency)`.
- HTTP/HTMX-запросы только от loopback-клиента.

### Выходы

- `SettingsSnapshot(settings_version, values, secret_presence)`.
- `settings.changed.v1(setting_key, settings_version, changed_at)`.
- Результат проверки зависимости: `ok`, `failed`, диагностический код и безопасное сообщение.

При несовпадении `expected_settings_version` команда завершается кодом `settings_version_conflict` без записи.

## 7. Data ownership

Модуль владеет сущностями:

- `OperatorSetting`: key, value type, active value, updated_at, settings version.
- `SettingChange`: change ID, key, old value, new value, reason, changed_at, source.
- `RuntimeSecretPresence`: вычисляемое, не сохраняемое представление наличия секрета.

Модуль не владеет содержимым секретов, Telegram session и настройками Task Scheduler.

## 8. Состояния и переходы

Обычная настройка проходит состояния `default → active → revised`; reset создаёт новый `SettingChange` и возвращает утверждённое default-значение. Секрет отображается только как `missing` или `configured`.

## 9. Ошибки, retries и recovery

- Ошибка валидации не повторяется автоматически.
- Конфликт версии требует перезагрузки формы и повторного ручного действия.
- Недоступность SQLite возвращает `503 settings_storage_unavailable` и не меняет runtime snapshot.
- После восстановления БД новый snapshot загружается целиком; частичное применение запрещено.

## 10. Security requirements

- HTTP listener — только loopback.
- Секретные значения не принимаются web-формами и не попадают в SQLite, журналы, метрики и экспорт.
- HTML responses используют `Cache-Control: no-store` для страниц диагностики конфигурации.
- Значения отображаются с HTML escaping; произвольный HTML в настройках запрещён.
- Изменение настроек допускается только POST-запросами с проверкой same-origin и CSRF token.

## 11. Observability

- Счётчики: `settings_update_total{result}`, `settings_validation_total{result}`, `dependency_check_total{dependency,result}`.
- Журналируются key, settings_version, result и duration без значений секретов.
- Health component `settings` имеет состояния `healthy` и `degraded`; `degraded` означает невозможность прочитать утверждённый snapshot.

## 12. Dependencies

- Upstream: Lead Storage (`Setting`, revisions, transaction), Security (секреты и local boundary), Deployment (environment и bind configuration).
- Downstream: Source Discovery, Collector, Detection, Scoring, Notifications, Dashboard и Observability.

## 13. MVP и исключённые функции

### MVP

- Локальные страницы настроек.
- Типизация, валидация, revisions и export без секретов.
- Диагностика Telegram session и уведомлений.

### DEFERRED

- Импорт пресетов rule sets через UI.
- Визуальное сравнение произвольных revisions.

### Исключено

- Multi-user, RBAC, remote access и web-редактирование секретов.

## 14. Acceptance test catalogue

- `SET-LOOPBACK`: AT-SET-001, AT-SET-002.
- `SET-VALIDATION`: AT-SET-003, AT-SET-004, AT-SET-005, AT-SET-006, AT-SET-010, AT-SET-011, AT-SET-014, AT-SET-015.
- `SET-SECRETS`: AT-SET-007, AT-SET-008, AT-SET-009, AT-SET-012, AT-SET-013.
- `SET-RECOVERY`: AT-SET-003, AT-SET-011.

## 15. Decision log references

- DEC-001: single-operator local product.
- DEC-006: secrets outside SQLite.
- DEC-007: loopback UI without login.
- DEC-011: RU-first UI and documentation.
