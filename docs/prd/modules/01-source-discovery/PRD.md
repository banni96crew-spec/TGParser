# Модульный PRD 01 — Source Discovery

## 1. Назначение и границы

Модуль формирует контролируемый реестр публичных Telegram-источников. Он принимает ручные ссылки и seed-списки, исследует рекомендации и связи между уже одобренными источниками, объединяет повторные находки и передаёт Collector только источник, вручную одобренный оператором.

Модуль не получает историю сообщений, не запускает live-подписку и не классифицирует сообщения.

## 2. Goals и non-goals

### Goals

- Находить публичные каналы, группы и супергруппы пятью утверждёнными способами.
- Не допускать мониторинг без явного действия единственного оператора.
- Обеспечить детерминированное объединение повторных кандидатов.
- Ограничить каждый discovery run фиксированным бюджетом.
- Сохранять полную техническую историю смены состояния источника.

### Non-goals

- Автоматическое присоединение к источникам.
- Поиск или обработка непубличных источников.
- Автоматическая оценка коммерческой ценности источника.
- Сбор сообщений и управление Telegram-сессией.
- AI/LLM-поиск или семантическое расширение seed-запросов.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Запуск discovery | Только вручную оператором |
| Максимальная глубина графа | `2` |
| Максимум новых кандидатов за run | `100` |
| Максимум Telegram-resolve операций за run | `25` |
| Identity priority | Telegram ID, затем normalized username |
| Начальное состояние находки | `candidate` |
| Начало monitoring | Только после ручного `approve` и успешной технической проверки |
| Поддерживаемые ссылки | `https://t.me/<username>`, `http://t.me/<username>`, `t.me/<username>`, `@<username>`, `<username>` |
| Seed import | UTF-8 CSV, заголовок `source_ref`, максимум `1000` строк |

## 4. Source lifecycle

```text
candidate -> approved -> monitoring
candidate -> rejected
monitoring <-> paused
monitoring -> inaccessible
inaccessible -> monitoring
monitoring/paused/inaccessible -> disabled
rejected -> candidate
```

| Переход | Инициатор | Условие |
|---|---|---|
| `candidate → approved` | Оператор | Нажатие `Approve` |
| `approved → monitoring` | Система | `TelegramGateway.validate_source` успешно подтвердил публичность и доступность |
| `candidate → rejected` | Оператор | Нажатие `Reject` с причиной из фиксированного enum |
| `rejected → candidate` | Оператор | Нажатие `Reconsider` |
| `monitoring → paused` | Оператор | Нажатие `Pause` |
| `paused → monitoring` | Оператор | Нажатие `Resume`, затем успешная техническая проверка |
| `monitoring → inaccessible` | Collector | Подтверждённая постоянная ошибка resolve/access |
| `inaccessible → monitoring` | Reconciliation | Успешная повторная техническая проверка |
| `monitoring/paused/inaccessible → disabled` | Оператор | Нажатие `Disable` |

`disabled` является терминальным состоянием MVP. История источника и ранее собранные данные физически не удаляются этим переходом.

Причины `rejected`: `off_topic`, `low_signal`, `duplicate_manual`, `not_needed`. Для `disabled`: `operator_disabled`.

## 5. Functional requirements

### SRC-001 — Ручное добавление

Система MUST принимать один public username или URL, нормализовать его и создавать discovery run с глубиной `0`.

Нормализация MUST:

1. удалить окружающие пробелы;
2. удалить схему и префикс `t.me/` без учёта регистра;
3. удалить начальный `@`;
4. удалить query string, fragment и завершающий `/`;
5. привести username к lower case;
6. отклонить значение, не соответствующее `^[a-z0-9_]{5,32}$`.

### SRC-002 — Импорт seed-списка

Система MUST принимать UTF-8 CSV с единственным обязательным столбцом `source_ref`, максимум `1000` строк и размером не более `1 MiB`. Пустые строки игнорируются. Каждая валидная строка обрабатывается как ручная находка одного run. Ошибочные строки сохраняются в result report с номером строки и кодом ошибки.

### SRC-003 — Методы discovery

Система MUST поддерживать методы `SourceDiscoveryEvent.method` (D-046):

1. `manual` — ручной public username или URL;
2. `seed_import` — импорт seed-списка;
3. `recommendation` — Telegram recommendations через `TelegramGateway.get_recommendations`;
4. `public_link` — публичные `t.me`-ссылки в сообщениях одобренных источников;
5. `mention` — `@username` в сообщениях одобренных источников;
6. `forward_origin` — origin публичных forwarded messages в одобренных источниках.

### SRC-004 — Контроль глубины

Ручная находка имеет depth `0`. Источник, найденный непосредственно из неё, имеет depth `1`. Источник из depth `1` имеет depth `2`. Находки глубже `2` MUST NOT ставиться на resolve и MUST фиксироваться счётчиком `depth_skipped_total`.

### SRC-005 — Бюджет run

Один run MUST создать не более `100` новых candidate records и выполнить не более `25` resolve операций. После достижения лимита оставшиеся references получают outcome `budget_skipped`; они не переносятся в следующий run автоматически.

Уже существующая запись не расходует лимит кандидатов. Проверка локального identity не расходует лимит resolve.

### SRC-006 — Порядок обхода

Очередь discovery MUST использовать breadth-first ordering: `depth ASC`, затем `discovered_at ASC`, затем normalized reference ASC. Такой порядок обеспечивает воспроизводимый расход бюджета.

### SRC-007 — Техническая проверка

Resolve MUST выполняться только через `TelegramGateway`. Валидным кандидатом является публичный `channel`, `megagroup` или `group`, для которого Gateway вернул Telegram ID, title, source type и public username. Пользователи, боты, private invite links и источники без public username получают outcome `unsupported_source`. Gateway adapter может принять Telethon `supergroup` только как внутреннее отображение в `megagroup`; в domain enum значение `supergroup` отсутствует.

### SRC-008 — Дедупликация кандидатов

После resolve система MUST искать существующий источник сначала по Telegram ID. При отсутствии ID-match выполняется поиск по normalized username. При совпадении обновляется alias/history существующей записи; новый `TelegramSource` не создаётся.

Если username у существующего Telegram ID изменился, старый username сохраняется как alias, новый становится current username.

### SRC-009 — Provenance

Каждая находка MUST сохранять `discovery_run_id`, method, depth, parent_source_id, raw_reference, normalized_reference и `discovered_at`. Для ручного ввода `parent_source_id=NULL`.

### SRC-010 — Ручное одобрение

Система MUST запрещать переход в `approved` без UI-команды оператора. Batch approve отсутствует. Каждое одобрение сохраняет timestamp и snapshot title/username/type.

### SRC-011 — Запуск monitoring

После `approve` система MUST выполнить свежую `validate_source`. Только успешный результат переводит источник в `monitoring` и публикует `SourceMonitoringRequested`. Ошибка оставляет состояние `approved` и показывает точный error code оператору.

### SRC-012 — Reject, reconsider, pause и disable

UI MUST реализовать все ручные переходы lifecycle. Каждая команда идемпотентна: повтор той же команды не создаёт дополнительного события и возвращает текущее состояние.

### SRC-013 — Атомарность

Изменение source state и создание outbox event MUST выполняться одной SQLite-транзакцией.

### SRC-014 — История состояния

Каждый фактический переход MUST создавать immutable `SourceApprovalEvent` с `source_id`, `from_state`, `to_state`, `reason_code`, `created_at` и `trigger` (`operator`, `collector`, `reconciliation`).

### SRC-015 — Повторный run

Повторный run с теми же seeds MUST быть безопасным: существующие sources получают дополнительный provenance record, но не дублируются и не меняют state автоматически.

### SRC-016 — Отчёт run

По завершении run система MUST показать: status, started/finished timestamps, число inputs, resolves, created candidates, merged candidates, invalid references, unsupported sources, budget skips, depth skips и errors.

## 6. Входные и выходные контракты

### Команды

| Команда | Обязательные поля | Результат |
|---|---|---|
| `StartDiscoveryRun` | `method`, `source_refs[]` или `parent_source_id` | `discovery_run_id` |
| `ApproveSource` | `source_id` | новое состояние или validation error |
| `RejectSource` | `source_id`, `reason_code` | `rejected` |
| `ReconsiderSource` | `source_id` | `candidate` |
| `PauseSource` | `source_id` | `paused` |
| `ResumeSource` | `source_id` | `monitoring` или validation error |
| `DisableSource` | `source_id` | `disabled` |

### События

| Событие | Обязательные поля |
|---|---|
| `SourceCandidateDiscovered` | `event_id`, `source_id`, `run_id`, `method`, `occurred_at` |
| `SourceMonitoringRequested` | `event_id`, `source_id`, `telegram_id`, `occurred_at` |
| `SourcePaused` | `event_id`, `source_id`, `occurred_at` |
| `SourceDisabled` | `event_id`, `source_id`, `occurred_at` |

Все события получают UUIDv7 `event_id` и записываются в transactional outbox.

## 7. Data ownership

Модуль владеет сущностями `TelegramSource`, `DiscoveryRun`, `SourceDiscoveryEvent`, `SourceAlias` и `SourceApprovalEvent`. Candidate является `TelegramSource` в состоянии `candidate`, отдельной candidate table нет. Collector владеет checkpoints и collection jobs, но не source state machine.

Ключевые ограничения:

- `TelegramSource.telegram_id` — unique, nullable только до первого resolve;
- `SourceAlias.normalized_username` — unique;
- один active `DiscoveryRun` одновременно;
- timestamps сохраняются в UTC с точностью до миллисекунд.

## 8. Ошибки, retry и recovery

- `FloodWait` передаётся Gateway и выдерживается полностью; discovery job переходит в `retry_wait`, а run остаётся `running` и затем продолжается с того же queue item.
- Сетевые ошибки получают до `5` попыток через `1`, `5`, `30`, `120`, `600` секунд.
- `USERNAME_NOT_OCCUPIED`, invalid username и unsupported entity не повторяются.
- Crash recovery продолжает run с первого queue item без terminal outcome.
- После пятой повторяемой ошибки item получает `failed`, а run продолжает остальные items.

## 9. Security requirements

- Source references и CSV не интерпретируются как HTML или shell input.
- CSV formula prefixes `=`, `+`, `-`, `@` экранируются апострофом только при формировании result export.
- Модуль не читает Telegram session-файл напрямую.
- В логах сохраняются source ID и error code; полный текст сообщений в логах отсутствует.

## 10. Observability

Метрики:

- `discovery_runs_total{status,method}`;
- `discovery_candidates_total{outcome,method,depth}`;
- `discovery_resolves_total{outcome}`;
- `discovery_run_duration_seconds`;
- `source_state_transitions_total{from,to,trigger}`;
- `discovery_budget_skipped_total{kind}`.

Structured log MUST включать `run_id`, `source_id`, `method`, `depth`, `outcome`, `duration_ms`, `error_code` без session credentials.

## 11. Dependencies

- `02-telegram-collector`: получает только `SourceMonitoringRequested`.
- `06-lead-storage`: транзакции, repositories и outbox.
- `07-lead-dashboard`: candidate review и ручные команды.
- `09-operator-settings`: фиксированные настройки отображения discovery.
- `10-administration-observability`: metrics, logs и run status.
- `11-security`: secrets boundary и log redaction.

## 12. MVP и исключённые функции

MVP включает SRC-001—SRC-016 полностью. Исключены semantic topic search, fuzzy source matching, автоматическое approval, batch approval, глубина выше `2` и расписание автоматических discovery runs.

## 13. Acceptance criteria и test catalogue

| ID | Требование | Сценарий | Ожидаемый результат |
|---|---|---|---|
| `AT-SRC-001` | SRC-001 | Ввести `https://t.me/Test_Channel/?x=1` | Получен `test_channel`; создаётся один run |
| `AT-SRC-002` | SRC-002 | Импортировать CSV с валидными, пустыми и ошибочными строками | Валидные обработаны; ошибки содержат номера строк |
| `AT-SRC-003` | SRC-003 | Запустить каждый из пяти методов | Provenance содержит точный method |
| `AT-SRC-004` | SRC-004 | Найти ссылку с depth `3` | Resolve не вызван; depth skip увеличен |
| `AT-SRC-005` | SRC-005 | Подать 150 уникальных валидных references | Создано не более 100 candidates и выполнено не более 25 resolves |
| `AT-SRC-006` | SRC-006 | Повторить run на одинаковом fixture | Порядок outcome идентичен |
| `AT-SRC-007` | SRC-007 | Resolve пользователя, private link и public channel | Candidate создаётся только для public channel |
| `AT-SRC-008` | SRC-008 | Найти один Telegram ID под старым и новым username | Один source, два aliases, новый current username |
| `AT-SRC-009` | SRC-009 | Найти источник через mention | Сохранены parent, method и depth |
| `AT-SRC-010` | SRC-010 | Завершить discovery без действий оператора | Все находки остаются `candidate` |
| `AT-SRC-011` | SRC-011 | Approve при успешной и ошибочной validation | Monitoring/event только при успехе |
| `AT-SRC-012` | SRC-012 | Дважды выполнить Pause | Состояние paused; один transition event |
| `AT-SRC-013` | SRC-013 | Инъецировать сбой outbox insert | State transition полностью откатан |
| `AT-SRC-014` | SRC-014 | Выполнить все допустимые переходы | История точна и immutable |
| `AT-SRC-015` | SRC-015 | Дважды запустить одинаковые seeds | Source не дублируется и state не меняется |
| `AT-SRC-016` | SRC-016 | Завершить mixed-outcome run | Все счётчики равны fixture |

## 14. Принятые записи decision log

- `DEC-SRC-001`: discovery запускается только вручную.
- `DEC-SRC-002`: graph depth равен `2`, candidate cap равен `100`, resolve cap равен `25`.
- `DEC-SRC-003`: любая находка сначала получает `candidate` и требует одиночного ручного approval.
- `DEC-SRC-004`: identity определяется Telegram ID, затем normalized username.
- `DEC-SRC-005`: private-source auto-join отсутствует.
