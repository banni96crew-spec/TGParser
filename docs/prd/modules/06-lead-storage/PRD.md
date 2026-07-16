# PRD модуля 06 — Lead Storage

## 1. Назначение и границы

Модуль предоставляет единственное authoritative хранилище продукта: SQLite schema, repositories, migrations, транзакционные границы, persisted jobs, transactional outbox, очистку, backup и restore. Модуль не содержит Telegram API logic, правил классификации, HTML и доставки уведомлений.

## 2. Goals

- атомарно сохранять message, lead, score и outbox event;
- переживать restart без потери jobs и недоставленных events;
- исключать дубликаты на уровне database constraints;
- сохранять историю revisions, scores и lead statuses в установленные сроки;
- поддерживать предсказуемый размер локальной БД;
- обеспечивать проверяемый backup и безопасный restore.

## 3. Non-goals

- PostgreSQL, Redis, Celery и внешняя message queue;
- несколько одновременно работающих application instances;
- хранение Telegram session в product database или backup;
- data warehouse и полнотекстовый поисковый кластер;
- downgrade migrations во время работы приложения.

## 4. Принятый стек

- SQLite;
- SQLAlchemy 2.x ORM/Core;
- runtime driver `aiosqlite`;
- Alembic migrations;
- встроенный SQLite online backup API;
- один Python process и один `DatabaseWriteCoordinator` для всех write transactions.

Runtime database находится в `%LOCALAPPDATA%\TelegramLeadDiscovery\data\app.db`. Backup находится в `%LOCALAPPDATA%\TelegramLeadDiscovery\backups`. Telegram session хранится отдельно и никогда не копируется модулем.

## 5. SQLite configuration

При каждом новом connection устанавливаются:

```text
PRAGMA foreign_keys=ON
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=5000
PRAGMA synchronous=NORMAL
```

- timestamps сохраняются в UTC в ISO 8601 с microseconds;
- enums закрепляются `CHECK` constraints или reference tables;
- network I/O внутри DB transaction запрещён;
- write transaction проходит через общий `DatabaseWriteCoordinator`;
- transaction длительностью более 1 секунды создаёт warning metric и log;
- scheduled bulk operations используют batches не более 500 строк.

## 6. Data ownership

Модуль владеет физической schema и migrations для всех сущностей. Логическим владельцем полей остаётся функциональный модуль.

### 6.1. Основные таблицы

| Таблица | Основные поля и constraints |
|---|---|
| `telegram_sources` | Telegram ID, normalized username, state, quality score |
| `telegram_messages` | source ID, Telegram message ID, current text, hash, state, timestamps |
| `telegram_message_revisions` | message ID, revision number, edited time, text, hash |
| `message_duplicates` | canonical ID, duplicate ID, method |
| `processing_results` | message revision, category, rule version, outcome |
| `rule_set_versions` | version, checksum, immutable content, activated time |
| `leads` | canonical message ID, category, band, status, current score ID, last activity |
| `lead_scores` | lead ID, score version, total, band, rule version, scored time |
| `lead_score_components` | score ID, rule ID, dimension, value, explanation |
| `lead_status_history` | lead ID, from/to, note, changed time |
| `lead_feedback` | lead ID, type, expected category, note, created time |
| `jobs` | type, payload, state, attempt, lease and schedule fields |
| `notification_outbox` | event type, entity IDs, schema version, idempotency key, state |
| `notification_deliveries` | outbox ID, attempt, status, response code, timestamps |
| `processing_logs` | run/message IDs, stage, outcome, error code, attempt, timestamp |
| `metric_samples` | metric name, dimensions, value, timestamp |
| `deleted_record_tombstones` | entity type, external identity hash, deleted time |
| `schema_migrations` | revision, checksum, applied time |

### 6.2. Обязательные constraints

- `UNIQUE(telegram_messages.source_id, telegram_messages.telegram_message_id)`;
- `UNIQUE(message_duplicates.duplicate_message_id)`;
- `UNIQUE(leads.canonical_message_id)`;
- `UNIQUE(notification_outbox.idempotency_key)`;
- `UNIQUE(rule_set_versions.version)`;
- `UNIQUE(rule_set_version, stable_rule_id)` для rules;
- `UNIQUE(lead_id, score_version)` для LeadScore;
- `UNIQUE(lead_id, scoring_job_id)` для защиты re-score replay;
- `CHECK(lead_scores.total BETWEEN 0 AND 100)`;
- `CHECK(telegram_sources.quality_score BETWEEN 0 AND 5)`;
- foreign keys включены, orphan records запрещены.

## 7. Transaction boundaries

### 7.1. New message

Одна short transaction выполняет insert-or-ignore по Telegram identity. Pipeline claim создаётся только для новой message revision.

### 7.2. Lead creation/update

Одна transaction:

1. сохраняет processing result;
2. создаёт или обновляет Lead;
3. сохраняет LeadScore и components;
4. устанавливает `current_score_id`, category и band;
5. при notification-eligible transition создаёт outbox event;
6. commit выполняется только после успешного завершения всех шагов.

Любая ошибка откатывает все шесть шагов.

### 7.3. Operator action

Изменение lead status, note, feedback, source quality или settings выполняется одной transaction и добавляет append-only history record.

### 7.4. Manual delete

Manual delete выполняется одной transaction:

1. создаётся tombstone без исходного текста;
2. удаляются связанные outbox и delivery rows;
3. удаляются feedback, status history, score components и scores;
4. удаляются lead, message revisions и message;
5. commit фиксирует удаление целиком.

При rollback все данные остаются в исходном состоянии. Tombstone не позволяет backfill повторно создать удалённую external identity.

## 8. Persisted jobs

Состояния:

```text
queued → running → succeeded
running → retry_wait → queued
running → failed
running/retry_wait → dead
queued/retry_wait → cancelled
```

- claim выполняется через conditional update внутри `BEGIN IMMEDIATE`;
- job lease длится `5 минут` и продлевается worker heartbeat каждые `60 секунд`;
- завершённый lease освобождается только после commit результата;
- job с истёкшим lease переводится `running → queued` при startup reconciliation;
- payload имеет `schema_version` и не содержит credentials;
- для каждого job type задаётся собственный bounded retry policy в owning module.

## 9. Transactional outbox

Состояния event:

```text
queued → delivering → sent
delivering → retry_wait → queued
delivering/retry_wait → dead
delivering с неизвестным результатом → dead (`delivery_uncertain`)
```

- event создаётся в transaction Lead изменения;
- payload содержит только schema version и IDs, полный message text не копируется;
- `idempotency_key` является unique;
- worker lease длится 60 секунд;
- повторный replay одного business event не создаёт вторую outbox row;
- delivery result и outbox state обновляются одной transaction;
- abandoned network attempt создаёт `NotificationDelivery(status=uncertain)` и переводит outbox непосредственно в `dead` с `delivery_uncertain`, без автоматической повторной отправки;
- `sent`, `dead` и delivery history удаляются через 30 дней.

## 10. Edits, deletes и deduplication

- уникальность Telegram message: `(source_id, telegram_message_id)`;
- edit добавляет revision с последовательным номером и обновляет `current_revision_id`;
- delete устанавливает `state=deleted` и `deleted_at`, а известный текст сохраняется до установленной очистки;
- exact cross-source duplicate определяется normalized text hash в окне 30 дней;
- canonical выбирается по `published_at`, затем internal source ID, затем Telegram message ID;
- Lead и outbox event создаются только для canonical message;
- duplicate message хранит связь с canonical и собственный provenance;
- fuzzy/semantic deduplication отсутствует в MVP.

## 11. Retention и scheduled cleanup

Cleanup запускается ежедневно в `04:00` по timezone `Europe/Moscow`. Каждая batch transaction обрабатывает не более 500 строк; continuation выполняется до полного завершения.

| Класс данных | Срок | Действие |
|---|---:|---|
| Leads, lead messages, scores, revisions, status history | 180 дней после `last_activity_at` | Удаление связанного graph и создание tombstone |
| Полный текст non-lead messages | 30 дней | `current_text` и revision text очищаются |
| Hash и processing outcome non-lead messages | 90 дней | Message graph удаляется |
| Processing logs | 30 дней | Rows удаляются |
| Metric samples | 90 дней | Rows удаляются |
| Notification deliveries/outbox terminal rows | 30 дней | Rows удаляются |
| Временные CSV files | 1 час | Files удаляются |

`Lead.last_activity_at` обновляется при message edit, новом score, status transition, note и feedback. Чтение lead и отправка notification его не меняют.

Cleanup никогда не удаляет active jobs, non-terminal outbox events, schema history и settings. Результат run содержит счётчики по каждому классу и duration.

## 12. Migrations

- каждое изменение schema оформляется Alembic revision;
- startup получает exclusive migration lock до запуска web и workers;
- перед upgrade создаётся pre-migration backup;
- revisions применяются последовательно;
- после upgrade выполняются `PRAGMA foreign_key_check` и `PRAGMA integrity_check`;
- при ошибке приложение закрывает connections, автоматически восстанавливает pre-migration backup и завершает startup с ошибкой;
- повторный startup безопасно применяет только отсутствующие revisions;
- ручное изменение production schema запрещено.

## 13. Backup и restore

### 13.1. Backup

- online backup запускается ежедневно в `03:00 Europe/Moscow`;
- используется SQLite backup API после passive WAL checkpoint;
- copy сначала записывается во временный файл;
- `PRAGMA integrity_check` должен вернуть `ok`;
- проверенная copy атомарно переименовывается;
- хранятся последние 7 ежедневных copies;
- воскресная copy дополнительно хранится как weekly; сохраняются 4 weekly copies;
- Telegram session и credentials не включаются;
- failed backup не заменяет последнюю исправную copy.

### 13.2. Restore

- application process должен быть остановлен;
- выбранная copy повторно проходит integrity check;
- текущая БД переименовывается в timestamped recovery file;
- copy атомарно устанавливается как `app.db`;
- startup применяет только более новые migrations и выполняет integrity checks;
- при любой ошибке восстановление прекращается, исходная БД возвращается на место.

## 14. Functional requirements

| ID | Требование | Приоритет | Acceptance criteria |
|---|---|---:|---|
| STO-001 | SQLite использует FK, WAL и busy timeout 5000 ms | MUST | PRAGMA probe подтверждает значения |
| STO-002 | Все writes проходят единый coordinator | MUST | Concurrent write test не создаёт lost update |
| STO-003 | Schema меняется только migration | MUST | Schema checksum соответствует migrations |
| STO-004 | Message identity защищена unique constraint | MUST | Replay не создаёт вторую row |
| STO-005 | Lead, score и outbox committed атомарно | MUST | Fault injection не оставляет partial graph |
| STO-006 | Jobs переживают restart | MUST | Незавершённый job возвращается в worker queue |
| STO-007 | Outbox event идемпотентен | MUST | Повтор business event даёт одну row |
| STO-008 | Cleanup применяет все сроки из §11 | MUST | Boundary tests удаляют только истёкшие данные |
| STO-009 | Manual delete атомарен | MUST | Fault injection приводит к полному rollback |
| STO-010 | Backup проверяется до публикации | MUST | Повреждённая copy не становится доступной для restore |
| STO-011 | Restore требует остановленного приложения | MUST | Команда отклоняется при active lock |
| STO-012 | Session отсутствует во всех backup artifacts | MUST | Artifact scan не находит session file |
| STO-013 | Все timestamps сохраняются в UTC | MUST | Round-trip не меняет момент времени |
| STO-014 | Exact duplicate window равен 30 дням | MUST | Сообщение за пределами окна не связывается |

## 15. Observability

Обязательные metrics:

- DB transaction duration и rollback count;
- SQLite busy/locked count;
- WAL size и checkpoint duration;
- job queue depth по state/type;
- outbox depth и oldest age;
- cleanup deleted count по классу;
- database file size;
- backup/restore duration и outcome;
- migration revision и outcome;
- integrity check outcome.

Logs содержат только internal IDs, operation, duration, row count и error code. Message text, credentials и session data не записываются.

## 16. Dependencies

- upstream business owners: Source Discovery, Collector, Processing, Detection, Scoring, Settings;
- downstream: Dashboard, Notifications, Administration/Observability, Deployment;
- runtime: Python 3.12.x, SQLite, SQLAlchemy 2.x, Alembic, aiosqlite.

## 17. Acceptance test catalogue

| Test ID | Проверка | Ожидаемый результат |
|---|---|---|
| AT-STO-001 | Два workers вставляют одну Telegram identity | Существует одна message row |
| AT-STO-002 | Ошибка после Lead до outbox insert | Transaction полностью откатывается |
| AT-STO-003 | Restart при running job | Job возвращается в queued после lease expiry |
| AT-STO-004 | Replay одного event | Unique key оставляет одну outbox row |
| AT-STO-005 | Non-lead text старше 30 дней | Текст очищен, hash сохранён |
| AT-STO-006 | Non-lead graph старше 90 дней | Graph удалён |
| AT-STO-007 | Lead inactive 180 дней | Lead graph удалён, tombstone сохранён |
| AT-STO-008 | CSV старше 1 часа | Файл удалён cleanup job |
| AT-STO-009 | Повреждённый backup | Integrity check блокирует публикацию |
| AT-STO-010 | Restore при запущенном приложении | Restore отклонён |
| AT-STO-011 | Migration fault | Backup восстановлен, startup завершён с ошибкой |
| AT-STO-012 | Cross-source exact repost | Один canonical lead и duplicate relation |
| AT-STO-013 | Manual delete fault | Все данные сохраняются через rollback |
| AT-STO-014 | Parallel UI и worker writes | Нет lost update и FK violation |

## 18. DEFERRED

- PostgreSQL migration path;
- read replicas;
- remote backup destination;
- encrypted database engine;
- fuzzy duplicate index.
