# Модульный PRD 01 — Source Discovery

## 1. Назначение и границы

Модуль формирует контролируемый реестр публичных Telegram-источников. Он принимает ручные ссылки и seed-списки, исследует рекомендации и связи между уже одобренными источниками, выполняет bounded keyword scouting публичных источников, объединяет повторные находки и передаёт Collector только источник, вручную одобренный оператором.

Модуль не получает историю сообщений для monitoring, не запускает live-подписку и не создаёт Lead из scouting-evidence.

## 2. Goals и non-goals

### Goals

- Находить публичные каналы, группы и супергруппы пятью утверждёнными graph-способами и keyword scouting.
- Не допускать мониторинг без явного действия единственного оператора.
- Обеспечить детерминированное объединение повторных кандидатов.
- Ограничить каждый discovery run фиксированным бюджетом.
- Оценивать полезность scouting-находок Source Opportunity Score без загрязнения Lead pipeline.
- Сохранять полную техническую историю смены состояния источника.

### Non-goals

- Автоматическое присоединение к источникам.
- Поиск или обработка непубличных источников.
- Автоматическое одобрение источников или включение monitoring.
- Создание Lead / notification из scouting-evidence.
- Платный search и Telegram Stars.
- Сбор monitoring-сообщений и управление Telegram-сессией.
- AI/LLM-поиск или семантическое расширение seed-запросов.
- Расписание автоматических keyword discovery runs.

## 3. Принятые решения

| Параметр | Значение |
|---|---|
| Запуск graph discovery | Только вручную оператором |
| Запуск keyword scouting | Только вручную оператором (D-057) |
| Максимальная глубина графа | `2` |
| Максимум новых кандидатов за graph run | `100` |
| Максимум Telegram-resolve операций за graph run | `25` |
| Identity priority | Telegram ID, затем normalized username |
| Начальное состояние находки / promotion | `candidate` |
| Начало monitoring | Только после ручного `approve` и успешной технической проверки |
| Keyword search mode | `free_only`; `allow_paid_stars` запрещён (D-050) |
| Active keyword runs | Не более одного одновременно (D-058) |
| Opportunity score owner | `SRC` (D-054); bands `promising`/`review`/`weak` |
| Evidence excerpt | Максимум `240` Unicode code points (D-056) |
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

### SRC-017 — Keyword discovery profile

Система MUST поддерживать `KeywordDiscoveryProfile` с уникальным `name` (`1..80`), состояниями `active|archived` и указателем `current_version`. Seed MVP MUST создать immutable профиль `ecommerce-development-ru` version `1` с post queries, directory queries и additional exclusions из утверждённого плана keyword discovery. Редактирование профиля MUST создавать новую version, не изменяя уже сохранённые версии.

### SRC-018 — Версионирование профиля

`KeywordDiscoveryProfileVersion` MUST хранить `post_queries_json` (`1..20`), `directory_queries_json` (`0..10`), `required_service_profiles_json`, `additional_exclusions_json`, `source_scope` (`groups|channels|all`). Каждый query после trim + casefold MUST иметь длину `3..128` Unicode code points; дубликаты запрещены. После ссылки из любого `DiscoveryRun` version MUST быть immutable (D-055). Run MUST фиксировать `profile_version_id`, активный `rule_set_version_id` и `rule_set_checksum`.

### SRC-019 — Ручной запуск keyword scouting

`StartKeywordDiscoveryRun` MUST приниматься только от UI-команды оператора (D-057). Система MUST отклонить старт, если уже существует active keyword run в `queued|running|retry_wait_flood|cancelling` (D-058), если profile version не active, или если Telegram credentials отсутствуют (`telegram_credentials_missing`). Успешный старт MUST одной транзакцией создать `DiscoveryRun(run_type=keyword_scouting, search_mode=free_only)`, развернуть `DiscoveryRunQuery` rows и `Job(job_type=keyword_discovery)`.

### SRC-020 — Бесплатные методы поиска

Keyword run MUST использовать только Gateway methods: `search_global`, `search_public_sources`, `search_source_messages`, и `search_public_posts` только после `check_public_post_search_quota` с подтверждённой бесплатной квотой (D-051). Paid search и любая передача `allow_paid_stars` запрещены (D-050). При Premium required или необходимости Stars query MUST получить `quota_skipped` без платежа; baseline free search продолжается. Принимаются только публичные `channel|megagroup|group` (D-048).

### SRC-021 — Граница scouting-evidence

`SourceDiscoveryEvidence` MUST NOT создавать `TelegramMessage`, `TelegramEventEnvelope`, `Lead`, `LeadScore`, notification outbox и MUST NOT изменять `CollectorCheckpoint` (D-052). Полный текст сверх excerpt, авторы и медиа MUST NOT сохраняться (D-056).

### SRC-022 — Дедупликация scouting-источников

Identity MUST применяться в порядке: `telegram_id` → существующий `TelegramSource.telegram_id` → current username → `SourceAlias` → normalized username fallback. Один Telegram ID MUST давать один `SourceOpportunitySnapshot` на run и может иметь несколько evidence rows.

### SRC-023 — Linked discussion

Для найденных каналов система MUST через Gateway `get_linked_discussion` искать связанную публичную discussion group с username. Linked discussion MUST сохраняться как отдельный opportunity result с `linked_parent_telegram_id` (D-053). Auto-join и автоматическое создание `TelegramSource` запрещены. Provenance method при promotion — `linked_discussion`.

### SRC-024 — Глубокая проверка источника

После seed search система MUST выбрать не более `25` источников для deep verification по предварительному рейтингу (число запросов, seed evidence, directory match, приоритет megagroup/linked discussion, свежесть, tie-break Telegram ID). На источник: максимум `5` **profile** queries из `KeywordDiscoveryProfileVersion` (`required_service_profiles` / profile-bound queries, not global `post_queries[:5]`), максимум `20` уникальных сообщений, окно `30` дней. Сообщения нормализуются и оцениваются pure DET `detect()`; результат пишется только в evidence. `required_service_profiles` и `additional_exclusions` MUST влиять на eligibility/score с explainable reason codes (SRC-045).

### SRC-025 — Source Opportunity Score

Система MUST рассчитывать детерминированный score `0–100`, принадлежащий `SRC` (D-054), по компонентам:

- qualified messages `0–40` (0/1/2/3/4/5+ → 0/8/16/24/32/40);
- regularity `0–25` по числу календарных недель с qualified (0/1/2/3/4+ → 0/8/14/20/25);
- ecommerce `0–20` = `min(20, ecommerce_qualified_count × 5)`;
- recency `0–15` (≤3d→15, 4–7d→10, 8–14d→5, >14d→0);
- noise penalty `0–30` = `floor(30 × excluded / max(1, qualified+excluded))`;
- `score = clamp(qualified + regularity + ecommerce + recency − noise, 0, 100)`.

Bands: `promising` `60–100`, `review` `35–59`, `weak` `0–34`. Plan prose aliases (D-067): `strong` ≡ `promising`, `moderate` ≡ `review` — enums MUST NOT be renamed. Tie-break: score DESC, qualified DESC, active weeks DESC, last qualified DESC, Telegram ID ASC. Score MUST NOT копироваться в `TelegramSource.quality_score`.

### SRC-026 — Продвижение в кандидаты

`PromoteOpportunityToCandidate` MUST по optimistic version и `review_state` создать `TelegramSource(candidate)` при отсутствии identity match либо связать существующий source без дубля. Method provenance: `keyword_search` или `linked_discussion`. Promotion MUST NOT вызывать `validate_source`, approval, checkpoint, backfill или monitoring (D-049). `DismissOpportunity` MUST помечать snapshot `dismissed` без создания source и MUST записывать durable suppress для будущих keyword scouting runs по identity order SRC-022.

### SRC-027 — Идемпотентность keyword команд

Повтор `StartKeywordDiscoveryRun` при активном keyword run MUST возвращать conflict без второго Job. Повтор `PromoteOpportunityToCandidate` / `DismissOpportunity` с тем же состоянием MUST быть идемпотентным: без второго source и без лишнего transition event. Повторное чтение Telegram page при том же cursor MUST подавляться unique constraints evidence/snapshot.

### SRC-028 — Отмена keyword run

Оператор MUST иметь возможность отменить active keyword run. Команда устанавливает `cancel_requested_at` на Job и переводит run в `cancelling`; worker MUST проверять флаг между сетевыми вызовами и завершать `cancelled`. Terminal `succeeded|partial|failed|cancelled` MUST NOT принимать повторный cancel как новую мутацию состояния.

### SRC-029 — Лимиты keyword run

Один keyword run MUST соблюдать:

- page size global search `50`, максимум `2` страницы на query/scope;
- отбрасывание hits старше `30` дней;
- общий cap `500` уникальных evidence; сверх лимита — `budget_skipped`;
- directory search максимум `20` peer results на query;
- deep verification максимум `25` источников;
- FloodWait: query `available_at=until`, Job `retry_wait`, run `retry_wait_flood`; worker MUST NOT долго спать в event loop;
- transient query retry максимум `3` attempts с delays `30`, `120`, `600` секунд.

### SRC-030 — Retention keyword artifacts

Ежедневный purge MUST применять:

| Данные | Срок |
|---|---:|
| `SourceDiscoveryEvidence.excerpt` | 30 дней |
| Evidence rows без текста | 90 дней |
| Unpromoted opportunity snapshots | 90 дней |
| Keyword `DiscoveryRunQuery` rows | 90 дней |
| Terminal keyword runs | 90 дней |
| Profile versions | без автоматического удаления |
| Promoted `SourceDiscoveryEvent` | существующая source provenance policy |

Batch максимум `500` rows за транзакцию. После очистки evidence UI MUST показывать «Доказательства очищены по retention policy», а не пустую ошибку.

### SRC-031 — Cross-run suppress registry sources (D-059)

Keyword scouting MUST suppress источники, уже присутствующие в Source Registry:

- match по identity order SRC-022 (`telegram_id` → registry `telegram_id` → username → alias);
- любой `lifecycle_state` реестра считается известным;
- suppressed `telegram_id` MUST NOT получать `SourceDiscoveryEvidence` и `SourceOpportunitySnapshot` в текущем run;
- suppressed `telegram_id` MUST NOT входить в deep-verification selection (≤25) и MUST NOT порождать linked-discussion opportunity;
- seed/directory/public_posts search MAY всё ещё получать hits от Telegram;
- run counter `registry_suppressed` MUST равняться числу **уникальных** suppressed `telegram_id` за run;
- SRC-022 внутри run сохраняется: один snapshot на новый (не suppressed) Telegram ID;
- dismissed suppress из SRC-032 применяется отдельно от registry suppress и использует тот же identity order.

### SRC-032 — Global dismiss suppress for future runs (D-060)

`DismissOpportunity` MUST создавать durable suppress-правило для будущих keyword scouting runs:

- match по identity order SRC-022 (`telegram_id` → registry `telegram_id` → username → alias);
- suppressed dismissed source MUST NOT получать `SourceDiscoveryEvidence` и `SourceOpportunitySnapshot` в любом следующем keyword run;
- suppressed dismissed source MUST NOT входить в deep-verification selection (≤25) и MUST NOT порождать linked-discussion opportunity;
- suppress MUST переживать retention `SourceOpportunitySnapshot` и MUST NOT зависеть только от `review_state` старого snapshot;
- повторный dismiss того же suppressed источника MUST оставаться идемпотентным;
- run counter `dismissed_suppressed` MUST равняться числу **уникальных** suppressed `telegram_id` за run.

### SRC-033 — Canonical source identity model

Система MUST представлять публичный источник через logical `CanonicalSourceIdentity` (D-061):

- `canonical_key` ∈ {`peer:<telegram_id>`, `username:<casefold>`};
- after resolve, canonical identity is Telegram numeric peer ID;
- linked `SourceAlias[]` remain owned by SRC (no dual owner);
- identity match order (frozen): `telegram_id` → registry `telegram_id` → current username → `SourceAlias` → provisional `username:<casefold>`;
- one canonical key per opportunity snapshot per run (extends SRC-022);
- promotion/suppress match MUST use `canonical_key`.

### SRC-034 — Provisional identity lifecycle and atomic merge

Unresolved username opportunities MUST use provisional key `username:<casefold>` until resolve (D-061):

- provisional identity MUST NOT reach `lifecycle_state=monitoring`;
- after resolve, transactional merge into `peer:<telegram_id>` MUST preserve dismiss provenance and aliases;
- merge emits existing `SourceApprovalEvent` / discovery merge outcomes — no second event owner.

### SRC-035 — Dismiss suppress ledger entity

Durable suppress ledger `DismissedSource` / `DismissedKeywordSource` MUST store (D-062 / SRC-032):

- `canonical_key`, nullable `telegram_id`, usernames/aliases JSON, `dismiss_reason`, `dismissed_at`, nullable `source_opportunity_id`, `operator_trigger`, version/upsert stamp;
- membership is permanent until explicit `ReconsiderDismissSuppress`;
- claim fields MAY upsert;
- the sole authoritative audit event for successful reconsider is `DismissSuppressReconsidered` (owner `SRC`); `SourceDiscoveryEvent` MUST NOT be used as an alternate or second authoritative reconsider channel;
- snapshot `review_state=dismissed` alone is NOT durable suppress.

### SRC-036 — ReconsiderDismissSuppress command

`ReconsiderDismissSuppress(canonical_key|suppress_id, note, CSRF, version)` MUST remove suppress membership only via that explicit action and MUST emit authoritative audit event `DismissSuppressReconsidered` (D-062 / SRC-035). It is distinct from `ReconsiderSource` (`rejected→candidate`). Re-dismiss remains idempotent (SRC-032).

### SRC-037 — Discovery run funnel counters and novelty

Completed keyword `DiscoveryRun` MUST persist funnel counters (D-063): `acquired_total`, `canonicalized_total`, `registry_suppressed`, `dismissed_suppressed`, `duplicate_in_run`, `cooldown_suppressed`, `qualified_total`, `presented_total`, `novel_presented_total`, `replacement_fetches_total`; `novelty_ratio = novel_presented_total / max(1, presented_total)`. Deterministic fixture with sufficient replacement pool: `novelty_ratio ≥ 0.80` after first run; dismissed recurrence across future runs = `0`. Live pilot: `5` sequential runs; median pairwise Jaccard of presented canonical sets ≤ `0.60` OR each violating run has proven `pool_exhausted=true` with reason.

### SRC-038 — pool_exhausted terminal reason codes

When replacement cannot fill presented quota, run MUST set `pool_exhausted=true` and `pool_exhausted_reason` from closed enum: `provider_empty`, `budget_cap_reached`, `quota_skipped_remaining`, `flood_wait_deferred`, `cancel_requested`, `no_unseen_after_suppress`.

### SRC-039 — Acquisition / qualification / presentation stages

Keyword worker MUST separate stages (D-063): `acquired` → `canonicalized` → `suppressed` → `qualified` → `presented`. Provenance MUST record provider method ∈ existing discovery methods + `keyword_search`/`linked_discussion`/`recommendation`/`public_link`/`mention`/`forward_origin`. Profile fields `required_service_profiles` and `additional_exclusions` apply under this stage model with SRC-024 caps.

### SRC-040 — Replacement acquisition after suppress

After registry/dismiss/cooldown suppress, worker MUST continue provider cursor/replacement fetches until presented quota (deep/qualification caps) OR `pool_exhausted` (D-063). Permanent dismiss (SRC-032) is not replaced by cooldown.

### SRC-041 — Cross-run presentation cooldown

Already-presented **non-dismissed** canonical identity MUST be hidden from default presentation for **24 hours** across keyword runs (`cooldown_suppressed`). Permanent dismiss suppress is not replaced by cooldown.

### SRC-042 — Graph edge types and public-only targets

Graph discovery MUST allow only closed public-only edge types: `recommendation`, `public_link`, `mention`, `forward_origin`, `linked_discussion` (SRC-003/023). Targets MUST be public `channel|megagroup|group` with resolvable public identity. Private/invite-only/unconfirmed username MUST NOT become candidates (`unsupported_source` / skip). Limits remain D-017 / SRC-004/005: `max_depth=2` (supersedes any plan prose `depth=1`), `candidate_cap=100`, `resolve/expansion_cap=25`, max outgoing edges examined per seed node = `25`, max unique graph candidates/run = `100`, one canonical node resolved at most once per run. FloodWait → provider phase `retry_wait` / run degraded with state preserved.

### SRC-043 — Evidence eligibility gates

Directory-only opportunities (no message/member/activity evidence) MUST NOT receive band `review` or `promising`; score forced into `weak` `0–34` with reason `directory_only_no_evidence`. Linked discussion / source lacking verification evidence → reason `needs_verification`; MUST NOT get `review`/`promising` (plan `moderate`/`strong` aliases) without deep verification.

### SRC-044 — Neutral noise sampling

Deep verification noise sample MUST include up to `20` messages in a `30`-day window that are neutral (not only exact-query hits), same caps as SRC-024.

### SRC-045 — Profile semantics enforcement

`required_service_profiles` MUST affect eligibility/score; `additional_exclusions` MUST apply with explainable reason codes. Profile semantics are owned by SRC opportunity path, not SCR.

## 6. Входные и выходные контракты

### Команды

| Команда | Обязательные поля | Результат |
|---|---|---|
| `StartDiscoveryRun` | `method`, `source_refs[]` или `parent_source_id` | `discovery_run_id` |
| `CreateKeywordDiscoveryProfile` | `name`, queries, scope | `profile_id` |
| `CreateKeywordDiscoveryProfileVersion` | `profile_id`, queries, scope, `version` | новая version |
| `StartKeywordDiscoveryRun` | `profile_id` | `discovery_run_id` |
| `CancelKeywordDiscoveryRun` | `run_id`, `version` | `cancelling`/`cancelled` |
| `PromoteOpportunityToCandidate` | `opportunity_id`, `version` | candidate source id |
| `DismissOpportunity` | `opportunity_id`, `reason`, `version` | `dismissed` + future keyword suppress |
| `ReconsiderDismissSuppress` | `canonical_key` \| `suppress_id`, `note`, `version` | suppress membership removed |
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
| `KeywordDiscoveryRunStarted` | `event_id`, `run_id`, `profile_version_id`, `rule_set_version_id`, `occurred_at` |
| `KeywordDiscoveryRunFinished` | `event_id`, `run_id`, `state`, funnel counters, `pool_exhausted`, `pool_exhausted_reason`, `novelty_ratio`, `occurred_at` |
| `SourceOpportunityPromoted` | `event_id`, `opportunity_id`, `source_id`, `method`, `occurred_at` |
| `DismissSuppressReconsidered` | `event_id`, `canonical_key` \| `suppress_id`, `note`, `occurred_at` |
| `SourceMonitoringRequested` | `event_id`, `source_id`, `telegram_id`, `occurred_at` |
| `SourcePaused` | `event_id`, `source_id`, `occurred_at` |
| `SourceDisabled` | `event_id`, `source_id`, `occurred_at` |

Все события получают UUIDv7 `event_id` и записываются в transactional outbox, где применимо для lifecycle transitions.

## 7. Data ownership

Модуль владеет сущностями `TelegramSource`, `DiscoveryRun`, `DiscoveryRunQuery`, `SourceDiscoveryEvent`, `SourceAlias`, `SourceApprovalEvent`, `KeywordDiscoveryProfile`, `KeywordDiscoveryProfileVersion`, `SourceDiscoveryEvidence`, `SourceOpportunitySnapshot`, logical `CanonicalSourceIdentity` и `DismissedSource` / `DismissedKeywordSource`. Candidate является `TelegramSource` в состоянии `candidate`, отдельной candidate table нет. Collector владеет checkpoints и collection jobs, но не source state machine. Physical suppress table and retention immunity are STO (STO-017).

Ключевые ограничения:

- `TelegramSource.telegram_id` — unique, nullable только до первого resolve / provisional;
- provisional identity MUST NOT enter `monitoring` (D-061 / SRC-034);
- `SourceAlias.normalized_username` — unique;
- не более одного active `graph` DiscoveryRun одновременно;
- не более одного active `keyword_scouting` DiscoveryRun одновременно (D-058);
- opportunity score не копируется в `quality_score` (D-054);
- timestamps сохраняются в UTC с точностью до миллисекунд.

## 8. Ошибки, retry и recovery

- `FloodWait` передаётся Gateway и выдерживается полностью; discovery job переходит в `retry_wait`, а run остаётся `running` (graph) или `retry_wait_flood` (keyword) и затем продолжается с сохранённого cursor/queue item.
- Сетевые ошибки graph discovery получают до `5` попыток через `1`, `5`, `30`, `120`, `600` секунд.
- Keyword query transient errors: максимум `3` attempts через `30`, `120`, `600` секунд; ошибка одной query обычно даёт run `partial`.
- `USERNAME_NOT_OCCUPIED`, invalid username и unsupported entity не повторяются.
- Unauthorized/frozen session переводит keyword run в `failed`.
- Crash recovery продолжает run с первого queue item / сохранённого cursor без terminal outcome.
- После исчерпания retry item/query получает `failed`, а run продолжает остальные items.

## 9. Security requirements

- Source references и CSV не интерпретируются как HTML или shell input.
- CSV formula prefixes `=`, `+`, `-`, `@` экранируются апострофом только при формировании result export.
- Модуль не читает Telegram session-файл напрямую.
- В логах сохраняются source ID, run ID, query ordinal, method, result count, error code и duration; полный текст сообщений, excerpts и authors в логах отсутствуют.

## 10. Observability

Метрики:

- `discovery_runs_total{status,method}`;
- `discovery_candidates_total{outcome,method,depth}`;
- `discovery_resolves_total{outcome}`;
- `discovery_run_duration_seconds`;
- `source_state_transitions_total{from,to,trigger}`;
- `discovery_budget_skipped_total{kind}`;
- `discovery_runs_total{state}` (keyword);
- `discovery_queries_total{kind,outcome}`;
- `discovery_search_hits_total{kind}`;
- `discovery_unique_sources_total`;
- `discovery_verified_sources_total`;
- `discovery_qualified_evidence_total`;
- `discovery_promotions_total{result}`;
- `discovery_flood_wait_seconds`;
- `discovery_quota_skipped_total`;
- `discovery_score_total{band}`.

Запрещённые metric labels: query text, source title, username, run ID, Telegram ID.

Structured log MUST включать `run_id`, `source_id`, `method`, `depth`, `outcome`, `duration_ms`, `error_code` без session credentials, excerpts и authors.

## 11. Dependencies

- `02-telegram-collector`: получает только `SourceMonitoringRequested`.
- `06-lead-storage`: транзакции, repositories и outbox.
- `07-lead-dashboard`: candidate review и ручные команды.
- `09-operator-settings`: фиксированные настройки отображения discovery.
- `10-administration-observability`: metrics, logs и run status.
- `11-security`: secrets boundary и log redaction.

## 12. MVP и исключённые функции

MVP включает SRC-001—SRC-045 полностью. Исключены semantic topic search, fuzzy source matching, автоматическое approval, batch approval, глубина выше `2`, платный search/Stars, создание Lead из evidence и расписание автоматических discovery runs.

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
| `AT-SRC-017` | SRC-017 | Создать/загрузить seed `ecommerce-development-ru` | Profile active; version `1` с утверждёнными queries |
| `AT-SRC-018` | SRC-018 | Изменить queries профиля после run | Создана version `2`; version `1` неизменна и referenced run сохраняет v1 |
| `AT-SRC-019` | SRC-019 | Запустить keyword run вручную при отсутствии active run | Созданы run+queries+Job; UI redirect на run |
| `AT-SRC-020` | SRC-020 | Free quota есть / Stars required / Premium required | Free search выполнен; paid/Premium → `quota_skipped`; `allow_paid_stars is None` |
| `AT-SRC-021` | SRC-021 | Завершить keyword run с hits | Нет `TelegramMessage`/Lead/outbox/checkpoint изменений |
| `AT-SRC-022` | SRC-022 | Один Telegram ID найден двумя queries | Один snapshot; ≥2 evidence rows |
| `AT-SRC-023` | SRC-023 | Канал с публичной linked discussion | Отдельный opportunity с `linked_parent_telegram_id`; join не вызван |
| `AT-SRC-024` | SRC-024 | Seed вернул >25 источников | Deep verification ≤25; per-source ≤20 messages / 30 дней |
| `AT-SRC-025` | SRC-025 | Фикстура qualified/weeks/ecommerce/recency/noise | Score и band совпадают с формулой; `quality_score` источника не изменён |
| `AT-SRC-026` | SRC-026 | Promote нового и существующего snapshot | Candidate создан один раз / linked; monitoring не стартовал |
| `AT-SRC-027` | SRC-027 | Повтор start при active run и повтор promote | Conflict / идемпотентный promote без дубля |
| `AT-SRC-028` | SRC-028 | Cancel во время running | `cancelling`→`cancelled`; сетевые вызовы прекращены после текущей page |
| `AT-SRC-029` | SRC-029 | Превысить evidence cap и получить FloodWait | `budget_skipped`; run `retry_wait_flood` до `until` |
| `AT-SRC-030` | SRC-030 | Evidence старше 30/90 дней | Excerpt/rows/snapshots/runs очищены по матрице |
| `AT-SRC-031` | SRC-031 | Registry содержит `telegram_id=X` (любой lifecycle); run находит hits для `X` и нового `Y` | Нет evidence/opportunity/deep query для `X`; opportunity только для `Y`; `registry_suppressed` ≥ 1 |
| `AT-SRC-032` | SRC-032 | В run-1 оператор dismiss-ит opportunity для `telegram_id=X`; run-2 снова находит hits для `X` и нового `Y` | В run-2 нет evidence/opportunity/deep query/linked discussion для `X`; opportunity только для `Y`; `dismissed_suppressed` ≥ 1 |
| `AT-SRC-033` | SRC-033 | Same peer under two usernames | One identity, two aliases |
| `AT-SRC-034` | SRC-034 | Unresolved username opportunity → provisional key; after resolve merge into peer | Dismiss provenance retained; monitoring blocked while provisional |
| `AT-SRC-035` | SRC-035 | Dismiss creates suppress row; purge snapshots | Suppress membership remains; recurrence = 0 |
| `AT-SRC-036` | SRC-036 | `ReconsiderDismissSuppress` then new run finds same peer | Opportunity may appear again; exactly one authoritative `DismissSuppressReconsidered`; distinct from `ReconsiderSource` |
| `AT-SRC-037` | SRC-037 | Fixture with sufficient replacement pool after first run | `novelty_ratio ≥ 0.80`; dismissed recurrence = 0 |
| `AT-SRC-038` | SRC-038 | Exhaust provider after suppress without quota fill | `pool_exhausted=true` with closed reason code |
| `AT-SRC-039` | SRC-039 | Trace single hit through stages | Stages `acquired→…→presented` recorded with provenance method |
| `AT-SRC-040` | SRC-040 | Suppress removes presented slot | Replacement fetch increases `replacement_fetches_total` until quota or exhaust |
| `AT-SRC-041` | SRC-041 | Present non-dismissed identity; second run within 24h | Hidden via `cooldown_suppressed`; after 24h eligible again |
| `AT-SRC-042` | SRC-042 | Private invite and depth-3 public link | Private skipped; depth>2 not resolved; depth stays `2`, caps `100`/`25` |
| `AT-SRC-043` | SRC-043 | Directory-only peer without message evidence | Band `weak`, reason `directory_only_no_evidence` |
| `AT-SRC-044` | SRC-044 | Deep sample includes non-query hits | ≤20 messages / 30d; neutral noise counted in exclusions |
| `AT-SRC-045` | SRC-045 | Profile with `required_service_profiles` + exclusion | Eligibility/score reflect profile; exclusion reason explainable |

## 14. Принятые записи decision log

- `DEC-SRC-001`: discovery запускается только вручную.
- `DEC-SRC-002`: graph depth равен `2`, candidate cap равен `100`, resolve cap равен `25`.
- `DEC-SRC-003`: любая находка сначала получает `candidate` и требует одиночного ручного approval.
- `DEC-SRC-004`: identity определяется Telegram ID, затем normalized username.
- `DEC-SRC-005`: private-source auto-join отсутствует.
- `D-048`–`D-058`: keyword scouting contract freeze (public-only, promote-only source creation, Zero Stars, free `searchPosts`, evidence isolation, linked discussion, SRC opportunity score, versioned profile/formula, excerpt ≤240, manual launch, single active keyword run).
- `D-059`: cross-run suppress registry-known sources (SRC-031).
- `D-060`: dismissed keyword result becomes durable future-run suppress (SRC-032).
- `D-061`: provisional identity + peer merge (SRC-033/034).
- `D-062`: suppress ledger + `ReconsiderDismissSuppress` (SRC-035/036).
- `D-063`: acquisition≠qualification, novelty, pool_exhausted (SRC-037..041).
- `D-067`: opportunity bands stay `promising|review|weak`; plan `strong|moderate` aliases only.
