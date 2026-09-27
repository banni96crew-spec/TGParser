Принял второй review. Ниже — версия плана после устранения оставшихся блокеров. Основные изменения:

* `Job(type=history_scan)` больше не считается подтверждённым — добавлен обязательный verification gate.
* `HistoryScanAnalyzer` получил явный immutable context.
* Убрана зависимость от `ProcessingResult`.
* Telegram retry/rate-limit вынесен в отдельный этап проверки владельца.
* Добавлены component ownership, cancellation, feature flag, rollback.

---

# Implementation Plan: Multi-Source Manual History Scan v2

## Goal

Добавить ручной запуск анализа истории нескольких Telegram-источников за выбранный период.

Пользователь:

1. выбирает источники;
2. задаёт период;
3. запускает сканирование;
4. получает список найденных вакансий/заявок.

Функция работает как отдельный аналитический режим.

Она:

* использует Telegram history;
* использует текущие Detection/Scoring правила;
* не создаёт monitoring Lead;
* не создаёт Notification;
* не изменяет Collector state.

---

# Scope

## In

* History Scan Session.
* Multi-source selection.
* Background execution.
* Telegram history retrieval.
* Read-only analysis.
* Result storage.
* UI.
* Migration.
* Tests.
* Feature flag.
* Retention.

## Out

* Backfill changes.
* Monitoring changes.
* Lead lifecycle changes.
* Notification pipeline changes.
* Detection rule changes.

---

# Current-state verification required before implementation

Перед кодированием необходимо проверить:

---

## 1. Existing Job system

Проверить:

```
storage/jobs.py
storage/models/*
runtime job dispatcher
```

Нужно подтвердить:

* Job model;
* допустимые `job_type`;
* enqueue API;
* claim mechanism;
* retry states;
* cancellation;
* recovery.

Только после этого выбрать:

### Option A

```text
HistoryScanSession
        |
        ↓
existing Job(type=history_scan)
```

если Job поддерживает:

* long-running jobs;
* custom types;
* cancellation.

---

### Option B

```text
HistoryScanSession
        |
        ↓
HistoryScanWorker
```

если текущий Job pipeline рассчитан только на короткие операции.

---

# Component ownership

| Component            | Responsibility        |
| -------------------- | --------------------- |
| Dashboard            | создание scan request |
| HistoryScanService   | lifecycle session     |
| Job/Worker           | execution scheduling  |
| Telegram adapter     | получение истории     |
| HistoryScanAnalyzer  | чистый анализ         |
| Storage repositories | persistence           |
| Cleanup job          | retention             |

---

# Decisions

# 1. HistoryScanResult не связан с ProcessingResult

## Решение

Использовать отдельную модель:

```
HistoryScanAnalysisResult
```

Причина:

Текущий `ProcessingResult` является частью ingestion pipeline и создаётся после:

* TelegramMessage;
* Revision;
* dedupe;
* processing state.

Создание его для history scan нарушает изоляцию.

---

Новая модель:

```text
HistoryScanResult

id
session_id
target_id

telegram_message_id
source_id

published_at

detection_category
score
band
explanation

created_at
```

---

# 2. Контракт анализа

## Новый контракт

Не:

```python
analyze(message)
```

а:

```python
analyze(
    message,
    AnalysisContext
)
```

---

## AnalysisContext

Immutable объект:

```python
AnalysisContext:

ruleset_version

ruleset_catalog

source_quality_score

scoring_parameters

thresholds

timezone
```

---

## Поток

```text
TelegramMessageDTO

        ↓

AnalysisContext

        ↓

Normalization

        ↓

Detection

        ↓

Scoring

        ↓

HistoryScanResult
```

---

## Гарантия parity

Monitoring:

```text
message
+
same AnalysisContext
=
Detection X
Score Y
```

History:

```text
same message
+
same AnalysisContext
=
Detection X
Score Y
```

---

# 3. Telegram ownership verification

Перед реализацией проверить:

```
collector/ports.py
collector/adapter/*
```

Определить владельца:

| Behavior          | Owner |
| ----------------- | ----- |
| FloodWait parsing | ?     |
| retry             | ?     |
| timeout           | ?     |
| rate limit        | ?     |
| reconnect         | ?     |

---

После проверки выбрать:

## Если Gateway уже владеет этим:

использовать Gateway.

---

## Если нет:

добавить только один уровень:

```text
HistoryScanService
        |
        ↓
TelegramGateway
        |
        ↓
existing retry/flood logic
```

Не создавать второй Telegram controller.

---

# 4. History Scan vs Backfill boundary

|                 | Backfill       | History Scan  |
| --------------- | -------------- | ------------- |
| Owner           | Collector      | HistoryScan   |
| Purpose         | восстановление | ручной анализ |
| Trigger         | internal       | UI            |
| Checkpoint      | изменяет       | нет           |
| TelegramMessage | создаёт        | нет           |
| Lead            | создаёт        | нет           |
| Result          | ingestion      | report        |

---

# Steps

---

# Step 0. Repository verification gate

## Files:

* `storage/jobs.py`
* `storage/models`
* `collector/adapter`
* `dashboard/routes`
* `dashboard/templates`

## Output:

Документированное решение:

* Job или Worker;
* retry owner;
* UI integration points.

## Validation:

Code evidence.

---

# Step 1. Add domain model

## Files:

* storage models
* Alembic migration

## Change:

Добавить:

```
history_scan_sessions

history_scan_targets

history_scan_results
```

---

## Session

```text
id

status

from_datetime
to_datetime

created_at
started_at
finished_at

cancel_requested_at
```

---

## Target

```text
id

session_id
source_id

status

messages_scanned
results_found

error_message
```

---

## Result

```text
id

session_id
target_id

source_id
telegram_message_id

published_at

category
score
band
explanation
```

---

## Validation

* migration up;
* insert/select;
* indexes;
* foreign keys.

---

## Rollback

Production:

* backup DB;
* disable feature;
* no downgrade with data.

---

# Step 2. Add HistoryScanService

## Responsibility:

Owns:

* session lifecycle;
* target lifecycle;
* progress.

Does not own:

* Telegram retry;
* detection;
* persistence details.

---

Methods:

```text
create_session()

start_session()

process_target()

cancel_session()

finish_session()
```

---

# Step 3. Integrate execution

После Step 0:

## If Job supported:

```text
HistoryScanSession

↓

Job

↓

Existing worker
```

---

## If not:

создать:

```text
HistoryScanWorker
```

---

Validation:

* restart;
* retry;
* cancellation.

---

# Step 4. Implement analyzer

## Files:

* processing/
* detection/
* scoring/

## Change:

Создать:

```python
HistoryScanAnalyzer
```

---

Input:

```python
TelegramMessageDTO
AnalysisContext
```

Output:

```python
HistoryScanAnalysisResult
```

---

Forbidden:

* DB writes;
* Lead creation;
* notification enqueue;
* checkpoint update.

---

Validation:

comparison tests:

Monitoring vs History.

---

# Step 5. Add dashboard

После проверки существующих routes.

Добавить:

```text
POST /history-scans
```

Создание.

```text
GET /history-scans/{id}
```

Progress.

```text
GET /history-scans/{id}/results
```

Results.

---

UI:

```
Sources

☑ Channel A
☑ Channel B

Period:

[24 hours]

Start
```

---

# Step 6. Concurrency controls

Добавить:

Settings:

```text
history_scan_enabled=true

max_active_sessions=1

max_sources_per_session=50
```

---

Validation:

* второй запуск блокируется;
* превышение лимита отображается пользователю.

---

# Step 7. Cancellation

Добавить:

```text
cancel_requested_at
```

Flow:

```text
User cancel

↓

DB flag

↓

worker checks flag

↓

stop next target
```

Текущий Telegram request:

* не прерывать принудительно;
* завершить корректно;
* сохранить состояние.

---

# Step 8. Retention

Добавить cleanup policy:

Например:

```text
history_scan_results: 30-90 days
history_scan_sessions: 180 days
```

Проверить существующий cleanup owner.

Не создавать новый scheduler без необходимости.

---

# Tests

## Unit

* lifecycle;
* context creation;
* analyzer parity;
* score calculation.

---

## Integration

### Multi-source

```text
5 sources

A OK
B OK
C fail
D OK
E OK
```

Expected:

```text
Session completed

failed_targets=1
```

---

### Isolation

Проверить:

```
CollectorCheckpoint unchanged

Lead unchanged

Outbox unchanged
```

---

### Telegram

После проверки owner:

* FloodWait;
* retry;
* timeout;
* reconnect.

---

### Migration

* upgrade;
* rollback policy verification;
* indexes.

---

# Risks

| Risk                                         | Likelihood | Impact  | Mitigation                      |
| -------------------------------------------- | ---------- | ------- | ------------------------------- |
| Job system не подходит для long-running scan | Средняя    | Высокий | Step 0 decision gate            |
| Разные результаты monitoring/history         | Средняя    | Высокий | AnalysisContext                 |
| Дублирование данных                          | Низкая     | Средний | отдельный analysis result       |
| Telegram rate limits                         | Высокая    | Средний | использовать существующий owner |
| Большая нагрузка SQLite                      | Средняя    | Средний | batch writes + indexes          |
| Незавершённые scans                          | Средняя    | Средний | cancellation/recovery           |

---

# Completion criteria

* [ ] подтверждён владелец execution lifecycle;
* [ ] выбран Job или Worker;
* [ ] реализован HistoryScanSession;
* [ ] несколько источников работают одним запуском;
* [ ] analyzer не создаёт side effects;
* [ ] Detection/Score совпадают с monitoring;
* [ ] checkpoint не меняется;
* [ ] Lead не создаются;
* [ ] Notification не создаются;
* [ ] FloodWait/retry используют один владеющий механизм;
* [ ] UI работает;
* [ ] migration безопасна;
* [ ] retention реализован.

---

# Open decisions

## 1. Job или отдельный Worker

Решается после проверки:

```
storage/jobs.py
dispatcher
retry model
```

---

## 2. Максимальная длительность scan

Нужно определить:

* максимальный период;
* максимальное число сообщений;
* поведение при превышении.

---

## 3. Нужно ли сохранять полный текст сообщения

Рекомендация:

нет.

Хранить:

* ссылку;
* telegram id;
* analysis result.

Полный текст получать через существующий message storage при необходимости.
