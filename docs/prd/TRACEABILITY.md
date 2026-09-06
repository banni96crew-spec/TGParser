# Requirements Traceability

## 1. Правило трассировки

Каждое module requirement `<PREFIX>-NNN` имеет acceptance test `AT-<PREFIX>-NNN` с тем же номером в PRD владельца. Таблица ниже является сводным индексом; точный scenario и expected result находятся в acceptance catalogue соответствующего модуля.

Изменение requirement без одновременного изменения одноимённого acceptance test запрещено.

## 2. Module requirements

| Module | Requirement range | Acceptance range | Owner document | Downstream verification |
|---|---|---|---|---|
| Source Discovery | `SRC-001..057` | `AT-SRC-001..057` | [PRD](modules/01-source-discovery/PRD.md) | Collector принимает только monitoring sources; scouting isolated; provisional identity + suppress reconsider; durable graph cursor/results; groups SEARCH + operator_seed; graph timeout skip and cancel |
| Telegram Collector | `COL-001..030` | `AT-COL-001..030` | [PRD](modules/02-telegram-collector/PRD.md) | Processing получает versioned envelopes; search ports Zero Stars; peer ref and sender kind for Telegram I/O; complete graph history response; graph call deadline |
| Message Processing | `PROC-001..019` | `AT-PROC-001..019` | [PRD](modules/03-message-processing/PRD.md) | Detection получает pinned version+checksum |
| Lead Detection | `DET-001..020` | `AT-DET-001..020` | [PRD](modules/04-lead-detection/PRD.md) | Scoring получает category/signals/rule IDs; SRC reuses pure detect; no silent SEED_RULES |
| Lead Scoring | `SCR-001..016` | `AT-SCR-001..016` | [PRD](modules/05-lead-scoring/PRD.md) | Storage/UI/Notifications получают immutable score |
| Lead Storage | `STO-001..025` | `AT-STO-001..025` | [PRD](modules/06-lead-storage/PRD.md) | Repositories, outbox, ActiveClientChat schema, suppress retention immunity, graph request-control and result persistence, suppress_class and profile v8 migrations, in-flight discovery reclaim exception |
| Lead Dashboard | `UI-001..029` | `AT-UI-001..029` | [PRD](modules/07-lead-dashboard/PRD.md) | End-to-end operator journeys включая `/discovery` defaults, `seed_refs` и graph run cancel |
| Notifications | `NOT-001..015` | `AT-NOT-001..015` | [PRD](modules/08-notifications/PRD.md) | Bot API adapter и outbox fault-injection suite |
| Operator Settings | `SET-001..015` | `AT-SET-001..015` | [PRD](modules/09-operator-settings/PRD.md) | Settings validation и local-access suite |
| Administration & Observability | `OBS-001..022` | `AT-OBS-001..022` | [PRD](modules/10-administration-observability/PRD.md) | Health, metrics, discovery novelty/loop health, capacity and durable terminal metrics |
| Security | `SEC-001..018` | `AT-SEC-001..018` | [PRD](modules/11-security/PRD.md) | Static scan, ACL, CSRF, Zero Stars, pseudonymous scouting authors, injection suite |
| Deployment & Infrastructure | `INF-001..023` | `AT-INF-001..023` | [PRD](modules/12-deployment-infrastructure/PRD.md) | Clean install, startup, named runtime loops, backup/restore suite, Telegram discovery execution lock |

## 3. Shared quality requirements

| Requirement | Primary modules | Acceptance suite |
|---|---|---|
| `NFR-PERF-001` | `COL`, `PROC`, `DET`, `SCR`, `STO` | Live pipeline load test |
| `NFR-PERF-002` | `STO`, `NOT` | Outbox-to-Bot latency test |
| `NFR-PERF-003` | `STO`, `UI` | Large local database UI benchmark |
| `NFR-PERF-004` | `DET`, `SCR` | DET-A performance corpus |
| `NFR-PERF-005` | `UI`, `STO` | Pagination contract test |
| `NFR-PERF-006` | `COL`, `STO`, `OBS`, `INF` | Capacity harness 100 sources / ≥1000 msg/day |
| `NFR-PERF-007` | `COL`, `PROC`, `STO`, `OBS` | Burst 10/s × 10 min; drain ≤15 min |
| `NFR-PERF-008` | `COL`, `PROC`, `STO`, `OBS` | p95 received→processed ≤30s / ≤120s burst |
| `NFR-REL-001` | `PROC`, `STO` | Exact replay suite |
| `NFR-REL-002` | `STO`, `NOT` | Outbox crash-boundary suite |
| `NFR-REL-003` | `COL`, `OBS` | Disconnect/reconciliation suite |
| `NFR-REL-004` | `INF`, `COL`, `STO`, `NOT` | Forced process restart suite |
| `NFR-REL-005` | `COL`, `STO` | Checkpoint transaction fault injection (envelope TX only; не `PersistProcessingResult`) |
| `NFR-REL-006` | `COL` | Fake FloodWait gateway test |
| `NFR-REL-007` | `STO`, `INF` | Migration/restore integrity suite |
| `NFR-REL-008` | `COL`, `PROC`, `STO`, `INF`, `OBS` | Kill/restart checkpoint resume; no gap/dup |
| `NFR-QLT-001` | `DET`, `SCR` | Corpus manifest validation |
| `NFR-QLT-002` | `DET`, `SCR`, `OBS` | Precision report (historical MVP; superseded for remediation by NFR-QLT-006) |
| `NFR-QLT-003` | `DET`, `SCR`, `OBS` | Direct-order recall report (historical MVP; superseded for remediation by NFR-QLT-006) |
| `NFR-QLT-004` | `DET`, `OBS` | Negative-category confusion matrix |
| `NFR-QLT-005` | `DET`, `SCR` | Deterministic repeated-run suite |
| `NFR-QLT-006` | `DET`, `SCR`, `SRC`, `OBS`, `UI` | Remediation calibration + discovery novelty gates (D-067) |
| `NFR-QLT-007` | `DET`, `SRC`, `UI`, `OBS` | Working-client-search DET precision/recall ≥80/80; discovery threshold owned by D-070 |
| `NFR-QLT-008` | `SRC`, `UI`, `OBS` | Live ActiveClientChat v1 plus explicit owner confirmation of three actionable evidence messages |
| `NFR-SEC-001` | `SET`, `SEC`, `INF` | Listener inspection |
| `NFR-SEC-002` | `SEC`, `STO`, `UI`, `INF` | Secret canary scan |
| `NFR-SEC-003` | `SEC`, `INF` | Windows ACL inspection |
| `NFR-SEC-004` | `SEC`, `UI` | CSRF/same-origin negative suite |
| `NFR-SEC-005` | `UI`, `NOT`, `SEC` | HTML/Telegram injection corpus |
| `NFR-SEC-006` | `DET` | Pathological regex suite |
| `NFR-MNT-001` | `COL` | Telethon import boundary scan |
| `NFR-MNT-002` | `UI`, `STO` | Route dependency scan |
| `NFR-MNT-003` | `STO`, domain modules | SQLAlchemy boundary scan |
| `NFR-MNT-004` | `INF` | Clean `uv sync --frozen` |
| `NFR-MNT-005` | `STO`, `INF` | Alembic metadata/head comparison |
| `NFR-MNT-006` | Все | Documentation ID lint |
| `NFR-OBS-001` | `STO`, `OBS` | Job detail integration test |
| `NFR-OBS-002` | `OBS`, все runtime modules | Health page component test |
| `NFR-OBS-003` | `OBS` | Structured event schema test |
| `NFR-OBS-004` | `OBS`, `STO` | Log/metric lifecycle test |
| `NFR-OBS-005` | `OBS`, `STO`, `NOT` | Critical alert idempotency test |
| `NFR-DATA-001` | `STO`, `UI` | Lead purge test |
| `NFR-DATA-002` | `STO` | Non-lead text purge test |
| `NFR-DATA-003` | `STO` | Non-lead graph purge test |
| `NFR-DATA-004` | `STO`, `UI`, `INF` | Temporary export cleanup test |
| `NFR-DATA-005` | `STO`, `INF` | Scheduler timezone test |
| `NFR-BCK-001` | `INF`, `STO` | Daily scheduler test |
| `NFR-BCK-002` | `INF` | Backup rotation fake-clock suite |
| `NFR-BCK-003` | `SEC`, `INF` | Backup content scan |
| `NFR-BCK-004` | `STO`, `INF` | Corrupt backup rejection test |
| `NFR-BCK-005` | `INF` | Running-process restore rejection test |

## 4. End-to-end journeys

| Journey | Requirements | Gate |
|---|---|---|
| Add and approve source | `SRC-001`, `SRC-007..014`, `COL-004..005`, `UI-006` | Candidate не мониторится до approve; backfill создаётся один раз |
| Keyword scouting → ActiveClientChat → promote → approve | `SRC-017..055`, `COL-021..027`, `DET-015..020`, `STO-015..024`, `UI-017..028`, `OBS-017..022`, `SEC-016..018`, `INF-021..022`, `NFR-QLT-008` | Public megagroup passes D-070; SEARCH provenance `global_message`; owner confirms 3 actionable messages; evidence ∉ Lead pipeline; Zero Stars; quality presented suppressed; operator_seed не заменяет SEARCH; promote → candidate only |
| Live lead | `COL-006`, `COL-023..026`, `PROC-001..004`, `PROC-019`, `DET-004..014`, `DET-016`, `SCR-001..013`, `STO-001..005`, `UI-002..005`, `NOT-001..008` | Lead виден ≤10 s; hot alert ≤30 s только при `delivery_mode=live`+secrets; в shadow Lead без outbox; peer-ref I/O |
| Disconnect recovery | `COL-007..010`, `COL-017..020`, `STO-010`, `STO-018`, `OBS-001..016`, `OBS-020..021`, `INF-002..010`, `INF-022` | Gap ≤20 min; duplicates `0`; named loops not deferred |
| Edit/delete/repost | `COL-013..015`, `PROC-005..014`, `STO-003..007`, `UI-012..014`, `NOT-009..015` | Revision/tombstone/canonical behavior детерминировано |
| Rule activation/re-score | `DET-001..006`, `DET-011..014`, `DET-016`, `PROC-019`, `SCR-001..016`, `UI-007..011` | Immutable versions; historical score не перезаписан; no SEED_RULES fallback |
| Backup/restore | `STO-010..014`, `SEC-001..017`, `INF-011..020` | Integrity `ok`; session отсутствует; runtime stopped; INF owns `BackupManifest` lifecycle |
| Capacity / remediation release | `NFR-PERF-006..008`, `NFR-REL-008`, `NFR-QLT-006`, `UI-021`, `OBS-021` | 100 sources / ≥1000 msg/day; burst drain; calibration gates; loopback only |

## 5. Release evidence

Release evidence включает:

- checksum active rule set и calibration corpus;
- requirement/test lint report;
- confusion matrix и latency percentiles;
- replay/fault-injection report;
- latest migration head;
- latest verified backup/restore result;
- secret scan result;
- список версий dependencies из lock-файла;
- remediation novelty/Jaccard и capacity harness evidence (Wave 09).

## 6. Phase 0 contract freeze notes (D-039..D-047)

- `AT-STO-NNN` ↔ `STO-NNN` 1:1 после D-043; см. catalogue в [06-lead-storage/PRD.md](modules/06-lead-storage/PRD.md).
- `AT-COL-018` terminal state = `dead` (не `failed`).
- `AT-COL-002/013/017` соответствуют shared `TelegramGateway` + `FloodWait(until)` + `message_*` event types.
- Critical codes OBS-012 / NOT: `collector_stopped`, `telegram_session_unavailable`, `migration_failed`, `integrity_check_failed`.
- Shadow (`notifications.delivery_mode`): см. [PHASE0_RESOLUTION_REGISTER.md](PHASE0_RESOLUTION_REGISTER.md) и D-047.

## 7. Keyword source discovery contract freeze (D-048..D-060)

- Decisions `D-048`–`D-058` accepted without gaps; см. [DECISION_LOG.md](DECISION_LOG.md).
- SRC requirements `SRC-017..032` ↔ `AT-SRC-017..032` 1:1; `D-059` / `SRC-031` registry suppress; `D-060` / `SRC-032` dismissed suppress.
- Cross-module MUST: `COL-021..022`, `DET-015`, `STO-015..016`, `UI-017..018`, `OBS-017..018`, `SEC-016..017`, `INF-021`.
- Shared domain entities: `KeywordDiscoveryProfile`, `KeywordDiscoveryProfileVersion`, `DiscoveryRunQuery`, `SourceDiscoveryEvidence`, `SourceOpportunitySnapshot`; `DiscoveryRun` extended with `run_type=keyword_scouting`.
- Gateway search ports and Zero Stars invariant documented in [INTEGRATION_CONTRACTS.md](shared/INTEGRATION_CONTRACTS.md).

## 8. Remediation contract freeze (D-061+)

- Decisions `D-061`–`D-069` freeze remediation without reopening D-059/D-060; см. [DECISION_LOG.md](DECISION_LOG.md).
- New/extended MUST 1:1 AT:
  - `SRC-033..050` ↔ `AT-SRC-033..050` (identity, suppress reconsider, novelty, acquisition, graph edges, eligibility, history quality gate, FloodWait resume, durable presented suppress D-069);
  - `COL-023..026` ↔ `AT-COL-023..026` (`TelegramPeerRef`, continuation, persist batch, live DTO); HistoryRequest purpose includes `scouting_verification` (D-068);
  - `PROC-019` ↔ `AT-PROC-019`; `DET-016` ↔ `AT-DET-016`; `DET-017` ↔ `AT-DET-017` (ru-mvp-2 provider-offer exclusions + ecommerce photo-for-site; corpus ≥80/80); `DET-018` ↔ `AT-DET-018` (ru-mvp-3 run14 precision; fair history waterfill; run-cap gate inconclusive);
  - `STO-017..019` ↔ `AT-STO-017..019` (truth_status columns);
  - `UI-019..026` ↔ `AT-UI-019..026` (truth buckets default, open Telegram, monitor handoff);
  - `OBS-019..021` ↔ `AT-OBS-019..021`;
  - `INF-022` ↔ `AT-INF-022`.
- Shared quality: `NFR-PERF-006..008`, `NFR-REL-008`, `NFR-QLT-006`; `NFR-QLT-007` retains historical DET corpus quality while D-070 owns discovery semantics.
- Band enum remains `promising|review|weak`; ActiveClientChat v1 mapping is truth-dependent exactly as SRC-025, while historical rows keep stored legacy bands.
- Graph depth remains `2` (D-017 / SRC-004 / SRC-042); plan Wave 04 `depth=1` does not override PRD.
- Wave 02 remains mandatory for historical suppress backfill + provisional identity schema (STO-017); empty migration head alone is insufficient.
- Product code for remediation begins only after Wave 01 PRD validator PASS.
- Historical D-068 live acceptance is superseded by D-070/NFR-QLT-008; unit/integration green still cannot claim product ready.

## 9. ActiveClientChat v1 contract freeze (D-070)

- D-070 supersedes D-068 qualification/score/truth/run gate and only the D-069 clause about two live PASS runs. The D-070 clause that SRC-041/SRC-050 remain unchanged is superseded by D-076.
- Updated owner requirements keep their existing AT IDs: `SRC-023`, `SRC-024`, `SRC-025`, `SRC-044`, `SRC-046`, `SRC-047`, `SRC-048`, `SRC-049`, `UI-025`, `NFR-QLT-007`.
- New 1:1 module requirements: `COL-027` ↔ `AT-COL-027`; `DET-019` ↔ `AT-DET-019`; `STO-021` ↔ `AT-STO-021`; `UI-027` ↔ `AT-UI-027`; `OBS-022` ↔ `AT-OBS-022`; `SEC-018` ↔ `AT-SEC-018`.
- `NFR-QLT-008` uses the shared quality acceptance/evidence mapping; `AT-NFR-QLT-008` does not exist.
- Automated completion is insufficient: release requires one live quality public megagroup with SEARCH/`global_message` provenance and explicit owner confirmation of three evidence messages. Until then status is not achieved.

## 10. Graph request-control isolation (D-071)

- Coverage ranges: `SRC-051..053`, `AT-SRC-051..053`, `COL-028..028`, `AT-COL-028..028`, `STO-022..022`, `AT-STO-022..022`, `INF-023..023`, `AT-INF-023..023`.
- `SRC-051` ↔ `AT-SRC-051`: 6-second spacing, rolling 10/minute, 200/run, durable reservation, first graph Flood terminal.
- `SRC-052` ↔ `AT-SRC-052`: graph cursor v2, stage reuse, current-node recovery and deterministic event idempotency.
- `SRC-053` ↔ `AT-SRC-053`: one active Telegram discovery mode across graph and keyword.
- `COL-028` ↔ `AT-COL-028`: context-only Telethon retry disabling, raw one-request graph operations, offline session cache and limit 100.
- `STO-022` ↔ `AT-STO-022`: migration `007`, nullable `access_hash`, conflict preflight and partial unique active-run index.
- `INF-023` ↔ `AT-INF-023`: shared runtime execution lock; keyword/global discovery cannot execute during graph.
- D-071 is a narrow exception to COL-017 and the D-070 resumable FloodWait rule only for `DiscoveryRun.run_type=graph`; keyword/history behavior is unchanged.

## 11. Durable graph results (D-072)

- Coverage ranges: `SRC-054` ↔ `AT-SRC-054`; `COL-029` ↔ `AT-COL-029`; `STO-023` ↔ `AT-STO-023`.
- `SRC-054`: graph post rows and cursor v3 stage receipt commit before the next Telegram call; saved stage never repeats the request.
- `COL-029`: one raw history response returns edges plus every message field required for durable qualification, with no per-message lookup.
- `STO-023`: migration `008`, unique post identity, provenance/request metadata, pseudonymous authors and 30/90-day retention.

## 12. Keyword SEARCH usefulness (D-073..D-076)

- Coverage: `SRC-017`, `SRC-019`, `SRC-020`, `SRC-024`, `SRC-037`, `SRC-040`, `SRC-041`, `SRC-049`, `SRC-050`, `SRC-055` ↔ same `AT-SRC-*`; `DET-020` ↔ `AT-DET-020`; `STO-024` ↔ `AT-STO-024`; `UI-028` ↔ `AT-UI-028`; `NFR-QLT-006`, `NFR-QLT-008`.
- D-073: groups-only `search_global`; posts bulk-skip after first Premium remains; SEARCH success = deep-verification occupancy.
- D-074: profile v8 empty directory + `source_scope=groups`; migration `010` only `7→8`; `ensure_seed` `{3,7,8}`; Directory reservation `0`; operator_seed lane; graph not invoked from keyword start.
- D-075: `ru-mvp-5` = `ru-mvp-4` + `NEG-ADV-020`; `ru-mvp-1..4` immutable.
- D-076: migration `009` `suppress_class`; match only `quality`; rejected MAY reappear; novelty only over quality.
- NFR-QLT-008 live: empty `seed_refs` first; `global_message`/`groups` `request_count>0` on buyer queries (step 1, not a substitute); quality from SEARCH/`global_message` + three owner-confirmed permalinks. Operator-seed quality is not a substitute.
- D-070 numeric thresholds MUST NOT be lowered. Graph and Stars remain out of this slice.

## 13. Graph hang hard-stop (D-077)

- Coverage: `COL-030` ↔ `AT-COL-030`; `SRC-056` ↔ `AT-SRC-056`; `SRC-057` ↔ `AT-SRC-057`; `UI-029` ↔ `AT-UI-029`; `STO-025` ↔ `AT-STO-025`.
- `COL-030`: one 30 s budget for graph exclusive wait + RPC; `GatewayTimeout` ≠ transient; orphan RPC allowed.
- `SRC-056`: timeout skips remaining stages empty, continues BFS; one transient `retry_wait` per node.
- `SRC-057`: `CancelGraphDiscoveryRun`, graph `cancelling`, Event interrupts wait, `cancelled` ≤30 s.
- `UI-029`: dispatcher on existing GET/POST discovery run paths; graph page without keyword HTMX fragments.
- `STO-025`: in-process `job_type=discovery` is not requeued by `recover_stale_jobs`.
