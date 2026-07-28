# Shared Domain Model

## 1. Общие правила

- Internal IDs — integer primary keys SQLite.
- Telegram IDs хранятся как signed 64-bit integers.
- Все timestamps хранятся в UTC ISO 8601 с timezone; UI преобразует их в `Europe/Moscow`.
- Enums фиксируются `CHECK` constraints.
- Foreign keys включены; orphan records запрещены.
- Текстовые hashes — lowercase SHA-256 hex.
- Каждая таблица имеет `created_at`; изменяемые aggregates имеют `updated_at`.

## 2. Ownership

| Entity | Owner |
|---|---|
| `TelegramSource`, `SourceAlias`, `SourceApprovalEvent`, `DiscoveryRun`, `DiscoveryRunQuery`, `SourceDiscoveryEvent`, `KeywordDiscoveryProfile`, `KeywordDiscoveryProfileVersion`, `SourceDiscoveryEvidence`, `SourceOpportunitySnapshot`, logical `CanonicalSourceIdentity`, `DismissedSource` / `DismissedKeywordSource`, logical `PresentedKeywordSource` | `SRC` |
| `TelegramAccount`, `CollectorCheckpoint`, `CollectionJob`, `TelegramEventEnvelope`, `TelegramPeerRef` (gateway DTO) | `COL` |
| `TelegramMessage`, `TelegramMessageRevision`, `DuplicateGroup`, `MessageDuplicate`, `ProcessingJob`, `ProcessingRun`, `ProcessingResult`, `ProcessingLog` | `PROC` |
| `RuleSetVersion`, `ServiceProfile`, `KeywordGroup`, `MonitoringRule`, `MatchedRule`, `DetectionResult` | `DET` |
| `LeadScore`, `LeadScoreComponent` | `SCR` |
| Physical schema, `Job`, `NotificationOutbox`, `DeletionTombstone`, `SchemaMigration`, purge metadata | `STO` |
| `Lead`, `LeadStatusHistory`, `LeadFeedback` | `UI` |
| `NotificationDelivery` | `NOT` |
| `OperatorSetting`, `SettingChange`, computed `RuntimeSecretPresence` | `SET` |
| `ComponentHealth`, `MetricBucket`, `AdminAction` | `OBS` |
| `BackupManifest` | `INF` |

Физическая persistence всех entities реализуется Storage, но смыслом и допустимыми переходами владеет указанный domain module.

## 3. Entities

### 3.1. Operator и settings

`OperatorSetting`

- `key: str` — primary logical key;
- `value_json: str`;
- `value_type: enum(string, integer, boolean, duration, string_list, object)`;
- `version: int >= 1`;
- `updated_at`.

`SettingChange`

- `id`;
- `setting_key`;
- `old_value_json`;
- `new_value_json`;
- `reason: str | null`;
- `changed_at`;
- `change_source: enum(ui, startup_seed, migration, system)`.

Reset to default записывает `reason=reset_to_default`.

### 3.2. Telegram account

`TelegramAccount`

- `id`;
- `account_ref: str` — безопасный локальный alias, не secret;
- `health_state: enum(disconnected, connecting, healthy, flood_wait, frozen, unauthorized, failed)`;
- `session_ref: str` — путь/alias вне product database content;
- `flood_wait_until`;
- `last_connected_at`;
- `last_update_at`.

В MVP существует ровно одна активная запись account.

### 3.3. Sources и discovery

`TelegramSource`

- `id`;
- `telegram_id: int | null`;
- `username_normalized: str | null`;
- `title: str`;
- `source_type: enum(channel, megagroup, group)`;
- `public_url: str | null`;
- `lifecycle_state: enum(candidate, approved, monitoring, rejected, paused, inaccessible, disabled)`;
- `quality_score: int 0..5`, default `2` после approve;
- `access_error_code: str | null`;
- `approved_at`, `monitoring_started_at`, `disabled_at`;
- `last_checked_at`.

Constraints:

- unique non-null `telegram_id`;
- unique non-null `username_normalized`;
- только `monitoring` может порождать collector jobs;
- provisional identity (`telegram_id IS NULL`, key `username:<casefold>`) MUST NOT enter `monitoring` (D-061).

`CanonicalSourceIdentity` (logical, owner `SRC`)

- `canonical_key: str` ∈ {`peer:<telegram_id>`, `username:<casefold>`};
- `telegram_id: int | null` — set after resolve;
- `username_normalized: str | null`;
- linked `SourceAlias[]` when merged into registry source;
- identity match order (frozen, extends SRC-022): `telegram_id` → registry `telegram_id` → current username → `SourceAlias` → provisional `username:<casefold>`;
- one canonical key per opportunity snapshot per run;
- after resolve, transactional merge into `peer:<telegram_id>` preserves dismiss provenance and aliases (D-061).

`SourceAlias`

- `id`, `source_id`;
- `normalized_username: str unique`;
- `valid_from`, `valid_until: timestamp | null`;
- current alias имеет `valid_until=NULL`.

`DismissedSource` / `DismissedKeywordSource` (logical suppress ledger, owner `SRC`; physical table `STO`)

- `id` / `suppress_id`;
- `canonical_key: str`;
- `telegram_id: int | null`;
- `usernames_json` / aliases;
- `dismiss_reason: str | null`;
- `dismissed_at`;
- `source_opportunity_id: int | null`;
- `operator_trigger: str | null`;
- `version` / upsert stamp — claim fields MAY upsert; membership is permanent until explicit `ReconsiderDismissSuppress` (D-062);
- retention MUST NOT delete suppress rows;
- snapshot `review_state=dismissed` alone is not durable suppress.

`PresentedKeywordSource` (logical already-shown suppress ledger, owner `SRC`; physical table `STO`; D-069 / SRC-041/050)

- `id`;
- `canonical_key: str` unique;
- `telegram_id: int | null` unique when set;
- `usernames_json` / aliases;
- `first_presented_at`;
- `origin_run_id: int | null`, `origin_opportunity_id: int | null`;
- `version` / upsert stamp — idempotent on re-presentation;
- retention MUST NOT delete presented-suppress rows (STO-020);
- snapshot presence alone after retention is not durable suppress.

`SourceApprovalEvent`

- `id`, `event_id: UUIDv7 unique`, `source_id`;
- `from_state`, `to_state`;
- `reason_code`;
- `trigger: enum(operator, collector, reconciliation)`;
- `note: str | null` length `0..1000`;
- `created_at`;
- append-only.

`KeywordDiscoveryProfile`

- `id`;
- `name: str` length `1..80`, unique;
- `state: enum(active, archived)`;
- `current_version: int`;
- `created_at`, `updated_at`.

Редактирование профиля MUST создавать новую `KeywordDiscoveryProfileVersion`, не мутируя использованную версию.

`KeywordDiscoveryProfileVersion`

- `id`;
- `profile_id`;
- `version: int`;
- `post_queries_json`;
- `directory_queries_json`;
- `required_service_profiles_json`;
- `additional_exclusions_json`;
- `source_scope: enum(groups, channels, all)`;
- `created_at`;
- unique `(profile_id, version)`.

Ограничения queries:

- `1..20` post queries;
- `0..10` directory queries;
- каждый query — `3..128` Unicode code points после trim + casefold;
- дубликаты запрещены;
- после использования в `DiscoveryRun` версия immutable (D-055).

Seed MVP: immutable profile `ecommerce-development-ru`, version `1`.

`DiscoveryRun`

- `id`;
- `run_type: enum(graph, keyword_scouting)` — default/legacy graph runs = `graph`;
- `root_source_ids_json` — для `graph`; nullable для keyword;
- `profile_version_id: int | null` — обязателен для `keyword_scouting`;
- `search_mode: enum(free_only)` — для keyword; paid modes отсутствуют (D-050);
- `rule_set_version_id: int | null`, `rule_set_checksum: str | null` — для keyword (D-055);
- `max_depth=2`, `expansion_cap=25`, `candidate_cap=100` — для `graph`;
- `state` для `graph`: `enum(queued, running, succeeded, failed, cancelled)`;
- `state` для `keyword_scouting`: `enum(queued, running, retry_wait_flood, cancelling, cancelled, succeeded, partial, failed)`;
- `phase: str | null` — для keyword (A–I);
- `quota_snapshot_json`, `cursor_json`, `last_error_code`;
- `version: int` — optimistic concurrency;
- counters и timestamps;
- remediation funnel counters (all `int ≥ 0`, keyword runs; D-063 / SRC-037 / D-069):
  - `acquired_total`, `canonicalized_total`, `registry_suppressed`, `dismissed_suppressed`,
  - `duplicate_in_run`, `presented_suppressed` (unique already-shown peers; `cooldown_suppressed` is alias),
  - `qualified_total`, `presented_total`,
  - `novel_presented_total`, `replacement_fetches_total`;
- `pool_exhausted: bool`;
- `pool_exhausted_reason: enum(provider_empty, budget_cap_reached, quota_skipped_remaining, flood_wait_deferred, cancel_requested, no_unseen_after_suppress) | null`;
- `novelty_ratio: float` = `novel_presented_total / max(1, presented_total)` for completed keyword runs.

`partial` означает, что часть queries пропущена из-за бесплатной квоты или permanent errors отдельных шагов.

Concurrency (D-058): не более одного active `keyword_scouting` run в состояниях `queued|running|retry_wait_flood|cancelling`. Graph discovery сохраняет отдельный лимит «не более одного active `graph` run».

`DiscoveryRunQuery`

- `id`, `run_id`, `ordinal`;
- `query_kind: enum(global_message, directory, public_posts, source_verification, linked_discussion)`;
- `query_text`;
- `source_telegram_id: int | null`;
- `scope: str | null`;
- `state: enum(queued, running, retry_wait, succeeded, failed, cancelled, quota_skipped, budget_skipped)`;
- `cursor_json`;
- `request_count`, `result_count`;
- `error_code: str | null`;
- `available_at`, `started_at`, `finished_at`.

`SourceDiscoveryEvidence`

- `id`, `run_id`;
- `source_telegram_id`, `source_username`, `source_title`, `source_type`;
- `telegram_message_id`, `published_at`, `permalink`;
- `excerpt: str` — максимум `240` Unicode code points (D-056);
- `normalized_hash`;
- `matched_query_ordinals_json`, `discovery_channels_json`;
- `detection_category`, `is_qualified`, `hard_exclusion`, `hard_exclusion_rule_id`;
- `service_profiles_json`, `rule_set_checksum`;
- `matched_rule_ids_json: list[str]` — stable DET rule IDs for UI explainability (D-068); default `[]`;
- `created_at`;
- unique `(run_id, source_telegram_id, telegram_message_id)`.

Запрещено хранить: author ID/username/display name, телефон, медиа, entities, полный текст сверх `excerpt` (D-056). Evidence MUST NOT становиться `TelegramMessage` / Lead (D-052).

`SourceOpportunitySnapshot`

- `id`, `run_id`;
- `source_id: int | null` — если источник уже в registry;
- `source_telegram_id`, `username`, `title`, `source_type`, `public_url`;
- `linked_parent_telegram_id: int | null`;
- `qualified_count`, `excluded_count`, `active_week_count`, `ecommerce_qualified_count`;
- `last_qualified_at`, `sample_message_count`, `sample_truncated`;
- `score: int 0..100`, `band: enum(promising, review, weak)`;
- `truth_status: enum(quality, near, inconclusive, rejected)` — working-client-search bucket (D-068 / SRC-046); default `inconclusive` until verification settles;
- `verification_scanned_count: int ≥ 0` — messages classified in history scan for this source/run;
- `verification_stop_reason: str | null`;
- `score_components_json`, `discovery_channels_json`;
- `review_state: enum(unreviewed, promoted, dismissed)`;
- `promoted_source_id: int | null`, `dismiss_reason: str | null`;
- `created_at`, `updated_at`, `version: int`;
- unique `(run_id, source_telegram_id)`.

Opportunity score принадлежит `SRC` (D-054) и MUST NOT копироваться в `TelegramSource.quality_score`.

Band mapping (frozen, D-054 / D-067): plan prose `strong` ≡ `promising` (`60–100`); `moderate` ≡ `review` (`35–59`); `weak` (`0–34`). Enums MUST NOT be renamed.

Truth status (D-068): `quality` (≥7 distinct clients / 14d); `near` (1–6); `inconclusive` (soft-cap/incomplete — «недоказанный»); `rejected` (completed 14d scan, 0 clients). Soft-cap MUST NOT map to `rejected`.

Keyword run counters (D-068 / SRC-047) additionally: `quality_sources`, `near_sources`, `inconclusive_sources`, `rejected_sources`, `globally_distinct_client_requests`, `history_scanned_total`, `gate_status` (`pass`|`fail`|`inconclusive`). Semantics: `pass` = ≥5 quality sources and ≥35 globally distinct client requests; `inconclusive` = run soft-cap `7500` reached before candidate pool exhausted without PASS; `fail` = pool exhausted (or otherwise finished) without PASS and without that run-cap-before-exhaustion path.

Eligibility reason codes (SRC opportunity, not SCR): `directory_only_no_evidence`, `needs_verification` — directory-only / unverified linked discussion MUST NOT receive `review` or `promising` without deep verification evidence.

`SourceDiscoveryEvent`

- `id`, `event_id: UUIDv7 unique`, `run_id`, `source_id: int | null`;
- `method: enum(manual, seed_import, recommendation, public_link, mention, forward_origin, keyword_search, linked_discussion)`;
- `parent_source_id: int | null`;
- `evidence_message_id: int | null`;
- `evidence_url: str | null`;
- `raw_reference`, `normalized_reference`;
- `outcome: enum(created, merged, invalid_reference, unsupported_source, budget_skipped, depth_skipped, error)`;
- `depth: int 0..2`;
- `discovered_at`.

Методы `keyword_search` и `linked_discussion` используются только при promotion scouting-результата в candidate (D-049, D-053).

### 3.4. Collector

`TelegramPeerRef` (gateway DTO, owner `COL`, schema_version=`1`)

- `telegram_peer_id: int | null`;
- `access_hash: int | null`;
- `username_normalized: str | null`;
- at least one of `telegram_peer_id` or `username_normalized` required;
- Gateway Telegram I/O MUST use `TelegramPeerRef`, never raw DB `source_id`, as Telethon entity (D-064).

`CollectorCheckpoint`

- `source_id`;
- `last_committed_message_id: int | null`;
- `last_committed_published_at`;
- `last_reconciled_at`;
- `version: int` для compare-and-swap.

`CollectionJob`

- application aggregate для `initial_backfill`, `startup_reconciliation`, `periodic_reconciliation` и `continuation`;
- использует physical `Job` table и общую job state machine;
- module `COL` владеет cursor, batch limits и retry semantics, `STO` — claim/lease.

`TelegramEventEnvelope`

- `event_id: str`;
- `event_type: enum(message_new, message_edited, message_deleted)`;
- `source_id`, `telegram_message_id`;
- `telegram_peer_id` — stable network identity paired with `telegram_message_id`;
- `observed_at`;
- `payload` — typed in integration contracts.

Envelope — application contract; отдельная таблица создаётся только для durable jobs/replay evidence. Mapping `telegram_peer_id` → monitoring `source_id` выполняется через Source Registry.

### 3.5. Messages и processing

`TelegramAuthor`

- `id`;
- `telegram_id: int | null`;
- `username: str | null`;
- `display_name: str | null`;
- `explicit_contact_text: str | null`;
- `last_seen_at`.

`TelegramMessage`

- `id`, `source_id`, `telegram_message_id`, `author_id`;
- `published_at`, `edited_at`, `deleted_at`;
- `original_text`, `normalized_text`;
- `normalized_hash`;
- `permalink: str | null`;
- `state: enum(active, edited, deleted)`;
- `canonical_message_id: int | null`;
- `last_processed_rule_version_id: int | null`.

Constraints:

- unique `(source_id, telegram_message_id)`;
- `canonical_message_id` не ссылается на duplicate;
- deleted message хранит последнюю известную revision до purge.

`TelegramMessageRevision`

- `id`, `message_id`, `revision_no`;
- `event_type: enum(create, edit, delete)`;
- `text`, `normalized_hash`;
- `observed_at`;
- unique `(message_id, revision_no)`.

`MessageDuplicate`

- `duplicate_message_id` primary key;
- `duplicate_group_id`;
- `canonical_message_id`;
- `method=exact_normalized_hash`;
- `window_days=30`;
- `linked_at`.

`DuplicateGroup`

- `id: int`;
- `group_key: str unique` — `<normalized_hash>:<UTC date earliest published_at>`;
- `canonical_message_id`;
- `created_at`, `updated_at`.

Group ID остаётся неизменным при смене canonical message.

`ProcessingJob`

- application aggregate для job types `process_message` и `replay_message`;
- использует physical `Job` table и общую job state machine из раздела 3.8;
- module `PROC` владеет payload и retry semantics, `STO` — physical claim/lease.

`ProcessingRun`

- `id`;
- `run_type: enum(live, backfill, reconciliation, rescore, calibration)`;
- `state: enum(queued, running, succeeded, partial, failed, cancelled)`;
- counters и timestamps.

`ProcessingResult`

- `id`, `message_id`, `revision_id`, `run_id`, `rule_set_version_id`;
- `category`;
- `score_total`, `score_band`;
- `hard_exclusion_rule_id: str | null`;
- `explanation_json`;
- `processed_at`;
- unique `(revision_id, rule_set_version_id)`.

`ProcessingLog`

- `id`, `run_id`, `message_id`;
- `stage: enum(claim, revision, normalize, identity_dedupe, repost_canonical, detect, score, persist, outbox, processing_ack)`;
- `outcome: enum(succeeded, skipped, retryable_error, permanent_error)`;
- `error_code: str | null`;
- `attempt: int >= 1`;
- `duration_ms >= 0`;
- `created_at`.

Стадия `checkpoint` отсутствует: `CollectorCheckpoint` принадлежит COL и не пишется processing pipeline.

### 3.6. Rules и scoring

`RuleSetVersion`

- `id`, `version: int unique`;
- `state: enum(draft, active, retired)`;
- `checksum: str unique`;
- `parent_version_id: int | null`;
- `created_at`, `activated_at`;
- active version immutable;
- partial unique constraint обеспечивает ровно одну active version.

`ServiceProfile`

- `id`, `rule_set_version_id`;
- `code: enum(websites, telegram_bots, integrations_api, automation_parsers, ecommerce)`;
- `display_name_ru`;
- `enabled`;
- unique `(rule_set_version_id, code)`.

`KeywordGroup`

- `id`, `rule_set_version_id`, `profile_id`;
- `code`;
- `rule_type`;
- `group_cap`;
- unique `(rule_set_version_id, code)`.

`MonitoringRule`

- `id`, `stable_rule_id: str`;
- `group_id`;
- `pattern: str`;
- `flags: str`;
- `dimension: str`;
- `weight: int`;
- `explanation_template_ru: str`;
- `enabled`;
- unique `(rule_set_version_id, stable_rule_id)` через group relationship.

`MatchedRule`

- `stable_rule_id`;
- `rule_type`;
- `dimension`;
- `weight`;
- `matched_excerpt: str` — максимум `120` Unicode code points.

`DetectionResult`

- `id`, `message_id`, `revision_id`, `rule_set_version_id`;
- `category`;
- `hard_exclusion: bool`;
- `matched_rules: list[MatchedRule]`;
- `service_profiles[]`;
- `explanation_items_ru[]`;
- `created_at`;
- unique `(revision_id, rule_set_version_id)`.

`LeadScore`

- `id`, `lead_id`, `processing_result_id`;
- `score_version: int >= 1`, монотонный внутри Lead;
- `rule_set_version_id`;
- `raw_total`, `soft_penalty_total`, `total`;
- `band: enum(hot, warm, cold, irrelevant)`;
- `scored_at`;
- unique `(lead_id, score_version)`.

`LeadScoreComponent`

- `id`, `lead_score_id`, `rule_id`;
- `dimension`;
- `value`;
- `reason_ru`.

### 3.7. Leads

`Lead`

- `id`, `canonical_message_id unique`;
- `current_score_id`;
- `category: enum(direct_order, contractor_search, recommendation_request, potential_need)`;
- `band: enum(hot, warm, cold, irrelevant)`;
- `status: enum(new, reviewed, contacted, won, lost, ignored, source_deleted)`;
- `last_activity_at`;
- `created_at`, `updated_at`.

Lead row создаётся только при первом committed score band ∈ `{hot, warm, cold}`. Rescore в `irrelevant` сохраняет существующий Lead и устанавливает `band=irrelevant`.

`LeadStatusHistory`

- `id`, `lead_id`;
- `from_status: str | null`, `to_status`;
- `note: str | null`;
- `changed_at`;
- append-only.

`LeadFeedback`

- `id`, `lead_id`;
- `feedback_type: enum(correct, false_positive, wrong_category, wrong_band)`;
- `expected_category: str | null`;
- `expected_band: str | null`;
- `note: str | null`;
- `created_at`.

### 3.8. Jobs, notifications и operations

`Job`

- `id`;
- `job_type: enum(discovery, keyword_discovery, initial_backfill, startup_reconciliation, periodic_reconciliation, continuation, process_message, replay_message, rescore, purge, backup)`;
- `dedupe_key: str unique`;
- `state: enum(queued, running, retry_wait, succeeded, failed, dead, cancelled)`;
- `payload_json`, `attempt`, `available_at`, `lease_until`;
- `cancel_requested_at: timestamp | null`;
- timestamps и error code.

Lease/idempotency invariants (D-066 / STO-018): lease `5 minutes`; heartbeat every `60 s`; expired lease → `running→queued` on startup/scan; transient retries `5` with delays `1, 5, 30, 120, 600` s where COL/PROC apply; unique inbox/envelope keys; unique outbox key; one unfinished collector job per `(source_id, type)` for activation. Keyword run-level states live on `DiscoveryRun`, not on `Job`.

`NotificationOutbox`

- `id`, `event_type`;
- `lead_id: int | null`;
- `incident_id: str | null`;
- `score_version: int | null`;
- `idempotency_key: str unique`;
- `state: enum(queued, delivering, retry_wait, sent, dead, cancelled)`;
- `available_at`, `created_at`.

Constraint: ровно одно из `lead_id` (для `hot_lead`) или `incident_id` (для critical event) не-null.

`NotificationDelivery`

- `id`, `outbox_id`, `attempt_no`;
- `destination_chat_ref`;
- `status: enum(sending, sent, retryable_error, permanent_error, uncertain)`;
- `response_code`, `error_code`;
- `attempted_at`;
- unique `(outbox_id, attempt_no)`.

`MetricBucket`

- `id`, `metric_name`, `labels_json`;
- `bucket_start`, `bucket_duration_seconds=300`;
- `count`, `sum`, `min`, `max`, percentile fields по metric type.

`ComponentHealth`

- `id`, `component`, `state: enum(starting, healthy, degraded, blocked, unhealthy, stopped)`;
- `reason_code`, `observed_at`, `last_success_at`.

`AdminAction`

- `id`, `action_type`, `target_type`, `target_id`;
- `result: enum(succeeded, rejected, failed)`;
- `correlation_id`, `created_at`.

`SchemaMigration`

- `version` primary key;
- `checksum`, `applied_at`.

`DeletionTombstone`

- `id`, `entity_type`;
- `external_identity_hash: str`;
- `deleted_at`;
- source text, contacts и secrets отсутствуют;
- unique `(entity_type, external_identity_hash)`.

`BackupManifest`

- semantic owner: `INF`;
- physical persistence: schema/migrations `STO`;
- `id`, `path_ref`, `backup_type: enum(daily, weekly)`;
- `database_checksum`, `database_size`, `schema_version`;
- `integrity_result: enum(ok, failed)`;
- `created_at`, `verified_at`.

INF владеет lifecycle (schedule, rotation, restore CLI, публикация manifest). STO предоставляет SQLite backup API primitives и integrity helpers.

## 4. Состояния источника

```text
candidate → approved → monitoring
candidate → rejected
monitoring ↔ paused
monitoring → inaccessible
inaccessible → monitoring
monitoring/paused/inaccessible → disabled
rejected → candidate
```

Недопустимый переход отклоняется в domain service до записи.

## 5. Score dimensions

| Dimension | Cap |
|---|---:|
| `intent` | 25 |
| `service_fit` | 20 |
| `specificity` | 15 |
| `budget` | 10 |
| `deadline` | 5 |
| `urgency` | 5 |
| `readiness` | 5 |
| `contactability` | 5 |
| `freshness` | 5 |
| `source_quality` | 5 |

Soft penalties ограничены `-30`; final total clamped to `0..100`.
