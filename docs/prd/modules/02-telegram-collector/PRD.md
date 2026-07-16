# Модульный PRD 02 — Telegram Collector

## 1. Назначение и границы

Модуль получает сообщения из вручную одобренных публичных Telegram-источников через одну пользовательскую сессию. Collector выполняет ограниченный backfill, принимает live updates и восстанавливает возможные пропуски reconciliation-задачами. Весь Telethon-код находится внутри `TelegramGateway`.

Collector публикует технические message envelopes и не анализирует смысл текста.

## 2. Goals и non-goals

### Goals

- Надёжно собирать backfill и новые сообщения без дубликатов downstream.
- Восстанавливать пропуски после restart или временного disconnect.
- Коммитить checkpoint только вместе с устойчиво сохранённым envelope.
- Полностью выдерживать `FloodWait`.
- Изолировать Telethon 1.44.x стабильным интерфейсом Gateway.

### Non-goals

- Несколько Telegram-аккаунтов и account rotation.
- Присоединение к источникам.
- Source discovery и approval.
- Нормализация, классификация, scoring и уведомления.
- Распределённая очередь или отдельный worker process.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Telegram library | Telethon `1.44.x` |
| Telegram boundary | Только `TelegramGateway` |
| Сессии | Одна пользовательская session |
| Первичный backfill | Последние `14 дней` или `3000` сообщений, что наступит раньше |
| Startup reconciliation batch | Не более `5000` сообщений от checkpoint |
| Periodic reconciliation | Каждые `15 минут`, не более `1000` сообщений на источник за batch |
| Продолжение при cap | Persisted continuation job |
| Live updates | Основной канал |
| Reconciliation | Восстановительный канал |
| Checkpoint | После успешного commit envelope |
| FloodWait | Полное ожидание указанного Telegram интервала |
| Runtime | Один Python-процесс, независимые asyncio services |

## 4. TelegramGateway

### COL-001 — Изоляция Telethon

Импорты `telethon.*`, создание клиента, MTProto requests и обработчики Telethon events MUST находиться только в package реализации `TelegramGateway`. Остальные модули работают с собственными DTO и exception types.

### COL-002 — Gateway interface

Gateway MUST предоставлять async-операции, совпадающие с shared `TelegramGateway` (D-039):

```text
connect() -> AccountSnapshot
disconnect() -> None
resolve_public_source(ref) -> SourceSnapshot
validate_source(ref | telegram_id) -> SourceSnapshot
get_recommendations(source, limit) -> list[SourceSnapshot]
iter_history(request) -> AsyncIterator[TelegramMessageDTO]
iter_updates() -> AsyncIterator[TelegramUpdateDTO]
get_message(source, message_id) -> TelegramMessageDTO | None
```

Методы `iter_messages` и `register_live_handler` запрещены. Live envelopes публикуются из `iter_updates`.

Gateway MUST преобразовывать library exceptions в `GatewayFloodWait(until)`, `GatewayUnauthorized`, `GatewayFrozen`, `GatewaySourceInaccessible`, `GatewayTransientError` и `GatewayPermanentError`.

### COL-003 — Session startup

При запуске приложение MUST подключить одну существующую пользовательскую session, вызвать `get_me` через Gateway и проверить совпадение Telegram user ID с сохранённым `expected_account_id`. Несовпадение или необходимость интерактивной авторизации блокирует Collector и создаёт critical health event.

## 5. Collection lifecycle

### COL-004 — Activation

`SourceMonitoringRequested` MUST создать idempotent backfill job и active subscription record. Для одного `source_id` допускается не более одного незавершённого job одного type.

### COL-005 — Initial backfill

Первичный backfill MUST получать сообщения newest-to-oldest до первого условия:

1. сообщение старше UTC timestamp `job_started_at - 14 days`;
2. принято `3000` сообщений;
3. история источника исчерпана.

Перед публикацией envelopes batch MUST быть переставлен oldest-to-newest. Backfill выполняется один раз для каждой активации source после `candidate/approved`; resume существующего source запускает reconciliation, а не новый initial backfill.

### COL-006 — Live updates

До запуска backfill jobs Gateway MUST начать `iter_updates` и публиковать envelopes для `message_new`, `message_edited` и `message_deleted`. Live envelope записывается немедленно в persisted inbox. Source state, отличный от `monitoring`, приводит к безопасному discard с metric; сетевой callback не выполняет классификацию.

### COL-007 — Startup reconciliation

После подключения и старта `iter_updates` система MUST создать для каждого monitoring source reconciliation job от `checkpoint.last_committed_message_id`, с batch cap `5000`. При достижении cap создаётся continuation job с новым cursor в той же транзакции, что и commit последнего envelope.

### COL-008 — Periodic reconciliation

Каждые `15 минут` scheduler MUST ставить reconciliation job каждому monitoring source. Один batch получает максимум `1000` сообщений после checkpoint. Достигнутый cap создаёт continuation job до исчерпания разрыва.

### COL-009 — Ordering

Backfill/reconciliation envelopes записываются в порядке `(published_at ASC, telegram_message_id ASC)`. Live updates могут прибывать раньше backfill; уникальный inbox key обеспечивает идемпотентность, а Message Processing определяет итоговую revision ordering.

### COL-010 — Checkpoint

Checkpoint содержит `source_id`, `last_committed_message_id`, `last_committed_published_at`, `last_reconciled_at`, `version` (compare-and-swap). Он изменяется только в той же SQLite-транзакции, где устойчиво сохранён соответствующий envelope (D-040). Значение message ID монотонно: `max(current, committed_message_id)`. `PersistProcessingResult` MUST NOT обновлять `CollectorCheckpoint`.

### COL-011 — Pause и disable

`SourcePaused` и `SourceDisabled` MUST перевести незапущенные jobs в `cancelled`, установить активному job `cancel_requested_at` и прекратить приём новых envelopes после текущей короткой транзакции. Resume выполняет validation и reconciliation от сохранённого checkpoint.

### COL-012 — Inaccessible source

`GatewaySourceInaccessible` с permanent code `USERNAME_NOT_OCCUPIED`, `CHANNEL_PRIVATE`, `CHANNEL_INVALID` или `CHAT_FORBIDDEN` MUST публиковать `CollectorSourceInaccessible`. Transient failures не меняют source state.

## 6. Envelope contracts

### COL-013 — Message envelope

Каждый envelope MUST содержать:

- UUIDv7 `event_id`;
- `event_type`: `message_new`, `message_edited` или `message_deleted`;
- internal `source_id`;
- Telegram `peer_id` и `message_id`;
- `published_at` UTC;
- `edited_at` UTC или null;
- `author_peer_id`, `author_username`, `author_display_name` при наличии;
- text или null;
- public message link при доступности;
- forward origin public peer/message IDs при наличии;
- `received_at` UTC;
- `collection_mode`: `backfill`, `live`, `startup_reconciliation`, `periodic_reconciliation`;
- `gateway_schema_version=1`.

Delete envelope (`message_deleted`) MUST содержать source/message IDs и `received_at`; текст не требуется.

### COL-014 — Idempotency key

Persisted inbox unique key: `(source_id, telegram_message_id, event_type, telegram_edited_at_or_epoch)`. Для delete вместо edit timestamp используется `received_at` с округлением до одной секунды и дополнительный partial unique constraint на незавершённый delete данного сообщения.

Повторный new envelope и повторный edit с тем же Telegram edit timestamp MUST не создавать новую inbox record.

### COL-015 — Public message link

Для source с public username ссылка формируется строго как `https://t.me/<username>/<message_id>`. При отсутствии username link равен null.

## 7. Jobs, retry и recovery

### COL-016 — Persisted jobs

Job имеет type `initial_backfill`, `startup_reconciliation`, `periodic_reconciliation` или `continuation`, state `queued`, `running`, `retry_wait`, `succeeded`, `failed`, `dead`, `cancelled`, cursor, attempt, `available_at`, `cancel_requested_at`, timestamps и last error code.

### COL-017 — FloodWait

При `GatewayFloodWait(until)` job переходит в `retry_wait`, `available_at=until` (точный UTC timestamp), attempt не увеличивается. Никакой другой Telegram job не стартует до `until`; account rotation отсутствует.

### COL-018 — Transient retry

Для transient network/RPC error применяются `5` повторов через `1`, `5`, `30`, `120`, `600` секунд. Между попытками job находится в `retry_wait`; после пятого неуспешного повтора получает `dead`. Permanent error сразу переводит job в `failed`. Collector health становится `degraded`, checkpoint остаётся на последнем commit.

### COL-019 — Restart recovery

При startup jobs с истёкшим `lease_until` возвращаются из `running` в `queued`. Job lease равен `5 минут`, heartbeat выполняется каждые `60 секунд`. Сохранённые cursor и checkpoint используются повторно. Inbox uniqueness MUST обеспечивать ноль дубликатов после replay.

### COL-020 — Connection recovery

При disconnect Gateway переподключается через `1`, `5`, `30`, `120`, затем каждые `300` секунд без ограничения числа попыток. После reconnect снова запускается `iter_updates` и startup reconciliation.

## 8. Data ownership

Модуль владеет `CollectorCheckpoint`, semantics `CollectionJob`, `TelegramEventEnvelope` и runtime health. Он не владеет `TelegramSource.state` и публикует запрос состояния его владельцу.

Ограничения:

- unique checkpoint per source;
- unique active job per `(source_id, job_type)`;
- timestamps UTC milliseconds;
- raw Telethon objects никогда не сериализуются в БД.

## 9. Security requirements

- Session path получается только из защищённой runtime-конфигурации.
- Session bytes, auth key, API hash и phone number не попадают в logs, metrics, exceptions UI или backup.
- Gateway принимает source identifiers как данные и не выполняет динамический Python-код.
- Web UI не предоставляет скачивание session-файла.

## 10. Observability

Metrics:

- `collector_updates_total{type,mode,outcome}`;
- `collector_job_duration_seconds{type,status}`;
- `collector_job_queue_depth{type}`;
- `collector_checkpoint_lag_messages{source_id}`;
- `collector_checkpoint_lag_seconds{source_id}`;
- `collector_floodwait_seconds_total`;
- `collector_reconnects_total{outcome}`;
- `collector_source_errors_total{code}`.

Health states: `starting`, `healthy`, `degraded`, `blocked`, `stopped`. `blocked` используется при auth/session failure; `degraded` — при failed job или disconnect с активным reconnect loop.

## 11. Dependencies

- `01-source-discovery`: source commands и state ownership.
- `03-message-processing`: consumer persisted inbox.
- `06-lead-storage`: jobs, inbox, checkpoint transactions.
- `10-administration-observability`: scheduler visibility, health и metrics.
- `11-security`: session/credential handling.
- `12-deployment-infrastructure`: lifecycle одного процесса.

## 12. MVP и исключённые функции

MVP включает COL-001—COL-020. Исключены multiple sessions, account rotation, distributed collectors, media download, reactions, comments outside separately approved sources и automatic join.

## 13. Acceptance criteria и test catalogue

| ID | Requirement | Сценарий | Ожидаемый результат |
|---|---|---|---|
| `AT-COL-001` | COL-001 | Статически найти `telethon` imports | Imports существуют только в Gateway package |
| `AT-COL-002` | COL-002 | Gateway contract test с fake adapter | Все DTO и exceptions стабильны |
| `AT-COL-003` | COL-003 | Session account не совпадает | Collector blocked; Telegram jobs не запущены |
| `AT-COL-004` | COL-004 | Дважды получить activation event | Один active backfill job |
| `AT-COL-005` | COL-005 | История 20 дней и 5000 сообщений | Получены максимум 14 дней и максимум 3000 сообщений |
| `AT-COL-006` | COL-006 | Live update приходит во время backfill | Envelope устойчиво сохранён один раз |
| `AT-COL-007` | COL-007 | Startup gap содержит 7000 сообщений | Первый batch 5000 и continuation без потери cursor |
| `AT-COL-008` | COL-008 | Periodic gap содержит 1500 сообщений | Batch 1000 и continuation 500 |
| `AT-COL-009` | COL-009 | Gateway отдаёт reverse history | Persisted sequence oldest-to-newest |
| `AT-COL-010` | COL-010 | Сбой commit envelope | Checkpoint не изменён |
| `AT-COL-011` | COL-011 | Pause во время batch | Завершена текущая транзакция; новые envelopes не приняты |
| `AT-COL-012` | COL-012 | Permanent и transient errors | State event только для permanent code |
| `AT-COL-013` | COL-013 | New/edit/delete fixtures | Envelope содержит точную schema v1 |
| `AT-COL-014` | COL-014 | Replay одного batch дважды | Inbox records не дублируются |
| `AT-COL-015` | COL-015 | Public username известен | Ссылка сформирована точно |
| `AT-COL-016` | COL-016 | Job проходит retry_wait и continuation | State transitions валидны и persisted |
| `AT-COL-017` | COL-017 | Gateway возвращает FloodWait с `until=now+90s` | Job ждёт до точного `until`, attempt неизменен |
| `AT-COL-018` | COL-018 | Пять transient failures | Delay sequence `1/5/30/120/600` точна; job `dead` после пятого retry |
| `AT-COL-019` | COL-019 | Process crash после envelope commit до ack | Restart даёт ноль duplicate inbox rows |
| `AT-COL-020` | COL-020 | Disconnect и reconnect | `iter_updates` восстановлен; startup reconciliation создан |

## 14. Принятые записи decision log

- `DEC-COL-001`: Telethon 1.44.x скрыт за `TelegramGateway`.
- `DEC-COL-002`: одна session и отсутствие account rotation.
- `DEC-COL-003`: initial backfill ограничен 14 днями или 3000 сообщениями.
- `DEC-COL-004`: startup batch равен 5000, periodic batch равен 1000, период равен 15 минутам.
- `DEC-COL-005`: checkpoint коммитится атомарно с envelope.
- `DEC-COL-006`: live updates являются основным каналом; reconciliation восстанавливает пропуски.
