# Shared Integration Contracts

## 1. Правила контрактов

- Domain modules не импортируют Telethon objects, SQLAlchemy models или HTTP client responses.
- DTO представлены immutable Python dataclasses/Pydantic models с явным `schema_version`.
- Текущая версия всех MVP DTO — `1`.
- Все команды имеют `command_id`; все события — `event_id`.
- Повтор команды с тем же idempotency key возвращает ранее committed result.
- Timestamps — UTC; IDs и enums соответствуют `DOMAIN_MODEL.md`.
- Breaking change повышает `schema_version` и одновременно обновляет producer, consumers и acceptance tests.

## 2. TelegramGateway port

Владелец: `COL`.

```python
class TelegramGateway(Protocol):
    async def connect(self) -> AccountSnapshot: ...
    async def disconnect(self) -> None: ...
    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot: ...
    async def get_recommendations(self, source: SourceRef, limit: int) -> list[SourceSnapshot]: ...
    async def iter_history(self, request: HistoryRequest) -> AsyncIterator[TelegramMessageDTO]: ...
    async def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]: ...
```

`PublicSourceRef`

- `schema_version=1`;
- `username_or_url`;
- private invite/import fields отсутствуют.

`HistoryRequest`

- `source_id`;
- `after_message_id` и/или `after_published_at`;
- `before_published_at`;
- `limit`;
- `purpose: backfill | startup_reconciliation | periodic_reconciliation`.

Gateway errors:

| Error | Поведение consumer |
|---|---|
| `GatewayFloodWait(until)` | Job → `retry_wait` до точного `until` |
| `GatewayUnauthorized` | Account → `unauthorized`, collector останавливается |
| `GatewayFrozen` | Account → `frozen`, collector останавливается |
| `GatewaySourceInaccessible` | Source → `inaccessible` после повторной проверки |
| `GatewayTransientError` | bounded retry с jitter |
| `GatewayPermanentError` | job failed, structured alert |

## 3. Source Registry port

Владелец: `SRC`, consumers: `COL`, `UI`, `SET`.

```python
class SourceRegistry(Protocol):
    async def add_candidate(self, command: AddCandidate) -> SourceCandidateResult: ...
    async def decide(self, command: SourceDecisionCommand) -> SourceSnapshot: ...
    async def list_monitoring(self) -> list[SourceSnapshot]: ...
    async def record_access_result(self, result: SourceAccessResult) -> SourceSnapshot: ...
```

Collector обязан вызвать `list_monitoring`; произвольный source ID из job payload недостаточен для Telegram call.

## 4. Telegram event envelope

Producer: `COL`, consumer: `PROC`.

```json
{
  "schema_version": 1,
  "event_id": "source_id:event_type:message_id:observed_at",
  "event_type": "message_new|message_edited|message_deleted",
  "source_id": 1,
  "telegram_message_id": 42,
  "observed_at": "UTC timestamp",
  "message": "TelegramMessageDTO|null"
}
```

`TelegramMessageDTO` содержит:

- Telegram identity;
- published/edited timestamps;
- text;
- author username/display name/explicit contacts, когда доступны;
- forward origin metadata;
- public permalink, когда его можно сформировать;
- service flags, нужные processing, без Telethon types.

Delete event может не содержать text или author.

## 5. Processing contract

Producer: `PROC`; consumers: `DET`, `SCR`, `STO`, `OBS`.

Порядок стадий фиксирован:

```text
source check
→ atomic claim
→ revision apply
→ normalization
→ Telegram identity dedupe
→ detection
→ scoring
→ exact repost dedupe
→ lead/non-lead persistence
→ transactional outbox
→ checkpoint
```

`NormalizedMessage`

- `message_id`, `revision_id`;
- `original_text`;
- `normalized_text`;
- `normalized_hash`;
- `published_at`;
- source и author context;
- `normalization_version=1`.

Normalization v1:

1. Unicode NFKC.
2. Lowercase через Unicode casefold.
3. Replace non-breaking spaces.
4. Collapse whitespace до одного space.
5. Trim.
6. URL/email/phone не удаляются.
7. Original text не изменяется.

## 6. Detection contract

Producer: `DET`, consumer: `SCR`.

`DetectionResult`

- `message_id`, `revision_id`;
- `rule_set_version_id`;
- `category`;
- `hard_exclusion: bool`;
- `matched_rules[]` с `stable_rule_id`, `rule_type`, `dimension`, `weight`, `matched_excerpt`;
- `service_profiles[]`;
- `explanation_items_ru[]`.

Для одного `revision_id + rule_set_version_id` результат детерминирован.

## 7. Scoring contract

Producer: `SCR`, consumers: `STO`, `UI`, `NOT`, `OBS`.

`ScoreResult`

- `message_id`, `revision_id`, `rule_set_version_id`;
- `category`;
- `components[]`;
- `raw_total`;
- `soft_penalty_total` в диапазоне `-30..0`;
- `total` в диапазоне `0..100`;
- `band`;
- `scored_at`;
- `explanation_items_ru[]`.

Hard exclusion возвращает `total=0`, `band=irrelevant` и ID исключающего правила.

## 8. Lead persistence command

Producer: `PROC`, owner: `STO`.

`PersistProcessingResult`

- message/revision data;
- detection result;
- score result;
- canonical/duplicate decision;
- checkpoint proposal;
- notification eligibility.

Одна SQLite transaction выполняет:

1. upsert message и revision;
2. insert processing outcome;
3. link duplicate либо create/update canonical Lead;
4. insert score/components;
5. insert outbox для eligible canonical hot lead;
6. commit checkpoint compare-and-swap.

При rollback ни один из шагов не виден consumers.

## 9. Notification contract

Producer: `STO` outbox, consumer: `NOT`.

`NotificationEvent`

- `event_type: hot_lead | collector_stopped | session_unavailable | migration_failed | integrity_failed`;
- `lead_id: int | null`;
- `score_version: int | null`;
- `idempotency_key`;
- `destination_chat_ref`;
- structured fields для template.

Hot lead payload:

- lead ID, band, score, category;
- source title;
- published time;
- excerpt максимум `500` characters;
- source permalink или local detail link.

Retries выполняются по offsets `0, 1, 5, 30, 120` минут от первого attempt. После пятого failure outbox state — `dead`.

## 10. UI application ports

Owner: соответствующий domain module, consumer: `UI`.

- `LeadQueryService`: filters, pagination, detail, score history.
- `LeadCommandService`: status transition, note, feedback.
- `SourceQueryService` и `SourceCommandService`.
- `RuleQueryService` и `RuleCommandService`.
- `JobQueryService` и `JobCommandService`.
- `HealthQueryService`.
- `SettingsService`.
- `ExportService`.

HTTP routes вызывают application ports; прямой SQL из route handlers запрещён.

## 11. Observability event

Каждый runtime component публикует structured event:

```json
{
  "schema_version": 1,
  "timestamp": "UTC",
  "level": "info|warning|error|critical",
  "component": "SRC|COL|PROC|DET|SCR|STO|UI|NOT|SET|OBS|SEC|INF",
  "event_code": "stable.code",
  "correlation_id": "run/job/message/outbox id",
  "duration_ms": 0,
  "fields": {}
}
```

Secrets, tokens, session content, raw environment и full message text запрещены в `fields`.

## 12. Job leasing

- Worker atomically claims one eligible job and sets `lease_until=now+5 minutes`.
- Heartbeat продлевает lease каждые `60 секунд` для long-running job.
- Истёкший lease переводит `running → queued` с incremented attempt.
- Один `dedupe_key` запрещает параллельные jobs одного назначения.
- Job completion и domain checkpoint сохраняются атомарно, когда находятся в одной database transaction.

Canonical job state machine:

```text
queued → running → succeeded
running → retry_wait → queued
running → failed
running/retry_wait → dead
queued/retry_wait → cancelled
```

`failed` означает permanent error; `dead` — исчерпанный retry budget. Запрос отмены running job хранится в `cancel_requested_at` и проверяется между короткими transactions.
