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
    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot: ...
    async def get_recommendations(self, source: SourceRef, limit: int) -> list[SourceSnapshot]: ...
    async def iter_history(self, request: HistoryRequest) -> AsyncIterator[TelegramMessageDTO]: ...
    async def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]: ...
    async def get_message(self, source: SourceRef, message_id: int) -> TelegramMessageDTO | None: ...
    async def search_global(self, request: GlobalSearchRequest) -> SearchPageDTO: ...
    async def search_public_sources(self, request: DirectorySearchRequest) -> list[SourceSnapshot]: ...
    async def check_public_post_search_quota(self, query: str) -> PublicPostSearchQuotaDTO: ...
    async def search_public_posts(self, request: PublicPostSearchRequest) -> SearchPageDTO: ...
    async def search_source_messages(self, request: SourceMessageSearchRequest) -> SearchPageDTO: ...
    async def get_linked_discussion(self, source: SourceRef) -> SourceSnapshot | None: ...
```

Методы `iter_messages` и `register_live_handler` отсутствуют. Live-канал — только `iter_updates`.

Search DTO (schema_version=`1`):

- `GlobalSearchRequest` — query, scope flags (`groups_only` / `broadcasts_only`), limit, cursor;
- `DirectorySearchRequest` — query, limit;
- `PublicPostSearchRequest` — query, limit, cursor; поле `allow_paid_stars` отсутствует и MUST NOT добавляться (D-050);
- `SourceMessageSearchRequest` — source ref, query, limit, date window, cursor;
- `SearchCursor` — opaque pagination token;
- `SearchMessageHitDTO` — source snapshot fields, `telegram_message_id`, `published_at`, permalink, text excerpt cap для consumer;
- `SearchPageDTO` — hits, next cursor, truncated flag;
- `PublicPostSearchQuotaDTO` — free slot available, Premium required, stars required amount;
- `LinkedDiscussionDTO` / return `SourceSnapshot | None` — public linked discussion only.

Zero Stars invariant (D-050, D-051): adapter MUST всегда передавать `allow_paid_stars=None` в raw Telethon `channels.SearchPostsRequest`; при `stars_amount > 0` без бесплатного слота запрос не выполняется.

Дополнительные Gateway errors:

| Error | Поведение consumer |
|---|---|
| `GatewayPremiumRequired` | Extended search channel skipped; baseline free search продолжается |
| `GatewaySearchQuotaExhausted` | Query / remaining extended queries → `quota_skipped` |
| `GatewayInvalidSearchQuery` | Query → `failed` без retry |
| `GatewaySearchUnavailable` | Query → `failed` или run `partial` по правилам SRC |

`PublicSourceRef`

- `schema_version=1`;
- `username_or_url`;
- private invite/import fields отсутствуют.

`TelegramPeerRef`

- `schema_version=1`;
- `telegram_peer_id: int | null`;
- `access_hash: int | null`;
- `username_normalized: str | null`;
- at least one of `telegram_peer_id` or `username_normalized` required.

`HistoryRequest`

- `source_id` — DB FK for jobs/checkpoints only; MUST NEVER be passed as Telethon entity (D-064 / COL-023);
- `peer: TelegramPeerRef` — mandatory for Gateway Telegram I/O;
- `after_message_id` и/или `after_published_at`;
- `before_published_at`;
- `limit`;
- `purpose: backfill | startup_reconciliation | periodic_reconciliation | continuation | scouting_verification`;
- `continuation_cursor: opaque | null` — for multi-page backfill beyond a single page.

Gateway MUST use `peer`, never raw DB `source_id`, as the Telethon entity. Persist batch size ≤ `50` envelopes per SQLite write TX; network I/O MUST remain outside long write transactions (COL-025).

`TelegramUpdateDTO` / live envelope identity:

- stable network identity `(telegram_peer_id, telegram_message_id)`;
- `event_type: message_new | message_edited | message_deleted`;
- maps to monitoring `source_id` via Source Registry;
- live filter: only sources with `lifecycle_state=monitoring`.

`TelegramMessageDTO.author_kind` (schema version 2 for new producer/consumers) is a closed enum `user|bot|channel|anonymous|unknown`. Gateway MAY expose raw `author_peer_id` in the in-memory DTO, but SRC scouting MUST transform a human user to source-scoped `author_key=SHA-256("active-chat-v1:" + source_telegram_id + ":" + author_peer_id)` before persistence. Raw scouting author identity MUST NOT enter persistence, logs, metrics, exports or UI. Pseudonymous `author_key` MAY persist only in evidence and cursor v2 for exact resume and follows their 90-day retention (COL-027/SEC-018).

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

## 3a. Keyword discovery contracts

Producer/owner: `SRC`; consumers: `UI`, `OBS`, `STO`; search I/O через `COL` `TelegramGateway`.

Команды:

| Команда | Обязательные поля | Результат |
|---|---|---|
| `CreateKeywordDiscoveryProfile` | `name`, queries, scope | `profile_id`, version `1` |
| `CreateKeywordDiscoveryProfileVersion` | `profile_id`, queries, scope, optimistic `version` | новая immutable version |
| `StartKeywordDiscoveryRun` | `profile_id`, CSRF, optimistic checks | `discovery_run_id`, Job `keyword_discovery` |
| `CancelKeywordDiscoveryRun` | `run_id`, optimistic `version` | state `cancelling` → `cancelled` |
| `PromoteOpportunityToCandidate` | `opportunity_id`, optimistic `version` | `TelegramSource(candidate)` или existing source link |
| `DismissOpportunity` | `opportunity_id`, reason, optimistic `version` | `review_state=dismissed` + durable suppress membership |
| `ReconsiderDismissSuppress` | `canonical_key` \| `suppress_id`, note, CSRF, optimistic `version` | removes suppress membership only; MUST emit authoritative `DismissSuppressReconsidered`; distinct from `ReconsiderSource` |

События / outcomes:

| Событие | Обязательные поля |
|---|---|
| `KeywordDiscoveryRunStarted` | `event_id`, `run_id`, `profile_version_id`, `rule_set_version_id`, `occurred_at` |
| `KeywordDiscoveryRunFinished` | `event_id`, `run_id`, `state`, funnel counters (`acquired_total`, `canonicalized_total`, `registry_suppressed`, `dismissed_suppressed`, `duplicate_in_run`, `presented_suppressed` / alias `cooldown_suppressed`, `qualified_total`, `presented_total`, `novel_presented_total`, `replacement_fetches_total`), `pool_exhausted`, `pool_exhausted_reason`, `novelty_ratio`, `occurred_at` |
| `SourceOpportunityPromoted` | `event_id`, `opportunity_id`, `source_id`, `method` (`keyword_search`\|`linked_discussion`), `occurred_at` |
| `DismissSuppressReconsidered` | sole authoritative audit for reconsider (owner `SRC`); `event_id`, `canonical_key` \| `suppress_id`, `note`, `occurred_at` |

Isolation (D-052): keyword search hits записываются только в `SourceDiscoveryEvidence` / `SourceOpportunitySnapshot`. Они MUST NOT публиковать `TelegramEventEnvelope`, MUST NOT создавать `TelegramMessage`/`Lead`/`LeadScore`/notification outbox и MUST NOT изменять `CollectorCheckpoint`.

Detection reuse: SRC вызывает pure DET evaluation на normalized scouting text через shared detect function / port с `analysis_text` и зафиксированными `rule_set_version_id` + checksum; результат сохраняется в evidence fields, не как pipeline `DetectionResult` row lead-path (см. DET-015 / DET-016). Pipeline detection MUST load rules only by pinned version+checksum; `SEED_RULES` is bootstrap-only (D-065).

Acquisition stages (machine-readable, D-063): `acquired` → `canonicalized` → `suppressed` → `qualified` → `presented`. Provider provenance method ∈ existing discovery methods + `keyword_search`/`linked_discussion`/`recommendation`/`public_link`/`mention`/`forward_origin`.

ActiveClientChat v1 (D-070): channel hits are ephemeral parents only; registry/dismiss/presented suppress is applied before `get_linked_discussion`; only an unsuppressed public `megagroup` enters verification. `DiscoveryRun.started_at` is the immutable reference `T`. Cursor schema v2 persists T, continuation, frozen counters including `unknown_author_message_count`, UTC active dates, source-scoped human author keys, request identities, request-author keys, normalized hashes, hard-exclusion count, latest request and stop state. Unknown-author count uses unique nonempty `[T-30d,T]` messages after Telegram identity then exact normalized-hash dedupe. FloodWait/crash returns a resumable state and MUST NOT publish terminal truth, metric or presented suppress.

Terminalization inserts `SourceOpportunitySnapshot` and immutable `DiscoveryTerminalOutcome` in one transaction. First inclusion of that terminal opportunity in a result set idempotently upserts `PresentedKeywordSource`. Before terminal transition the opportunity MUST NOT be visible or suppressed.

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

Порядок стадий фиксирован (D-040):

```text
claim
→ revision
→ normalize
→ identity dedupe
→ exact repost canonical
→ detection
→ scoring
→ persist lead/outbox
→ processing ack
```

`CollectorCheckpoint` не входит в processing stages: он обновляется только COL в той же SQLite-транзакции, что и durable envelope inbox write.

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
- `matched_rules[]` с `stable_rule_id`, `rule_type`, `dimension`, `weight`, `matched_excerpt` (максимум `120` Unicode code points);
- `service_profiles[]`;
- `explanation_items_ru[]`.

`matched_excerpt` — UTF-8 substring `analysis_text`, покрывающий regex match; при zero-width — пустая строка. В structured logs excerpt не записывается.

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
- notification eligibility;
- processing completion ack.

Одна SQLite transaction выполняет:

1. upsert message и revision;
2. insert processing outcome;
3. link duplicate либо create/update canonical Lead;
4. insert score/components;
5. insert outbox для eligible canonical hot lead (только при `notifications.delivery_mode=live` и наличии notification secrets);
6. processing inbox/job completion ack.

`PersistProcessingResult` MUST NOT мутировать `CollectorCheckpoint`. Checkpoint compare-and-swap выполняется только COL вместе с envelope write.

При rollback ни один из шагов не виден consumers.

## 9. Notification contract

Producer: `STO` outbox, consumer: `NOT`.

`NotificationEvent`

- `event_type: hot_lead | collector_stopped | telegram_session_unavailable | migration_failed | integrity_check_failed`;
- `lead_id: int | null`;
- `incident_id: str | null`;
- `score_version: int | null`;
- `idempotency_key`;
- `destination_chat_ref`;
- structured fields для template.

Для `hot_lead` обязателен `lead_id` (+ `score_version`); для critical events обязателен `incident_id`. Ровно одно из двух присутствует: lead или incident.

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
- `KeywordDiscoveryQueryService` и `KeywordDiscoveryCommandService`.
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
