# Wave 01 — Architect contract delta map (READ-ONLY product/docs; evidence write only)

- **Agent:** architect
- **Captured_at:** 2026-07-27 (Wave 01)
- **Plan:** `~/.cursor/plans/telegram-lead-discovery-remediation_7067172d.plan.md` Wave 01 + §2 + ADR-PLAN-001..006
- **Inputs:** Wave 00 explorer/planner/architect/critic/implementation; current `docs/prd/*`; D-059/D-060; SRC-031/032
- **Repo HEAD (Wave 00):** `f1b9445` on `main` (re-verify before writer edits)
- **Status:** **PASS** — writer handoff **ready**
- **Product code / PRD edits by this agent:** none

---

## Architecture Analysis

### Summary

Wave 01 must **document-freeze** remediation contracts already decided by ADR-PLAN-001..006, plan §2 success gates, D-059/D-060, and Wave 00 HOLD-WITH-NOTES — without reopening product forks (no AI, outreach, private auto-join, Stars). Existing `SRC-001..032` / `COL-001..022` / etc. are **reused and extended**; new IDs start at the next free number per module (`SRC-033+`, `COL-023+`, …). Opportunity bands stay `promising|review|weak` (D-054); plan prose `moderate/strong` **maps** to `review/promising`. Graph depth stays **`2`** (D-017/SRC-004); Wave 04 plan line `depth=1` is superseded by existing PRD per plan Wave 04 note. Suppress “append-only” = permanent membership until explicit `ReconsiderDismissSuppress`; claim fields MAY upsert. Wave 02 remains mandatory (historical backfill + semantics).

### Binding notes (from Wave 00 Critic/Architect — do not weaken)

1. HC-5 UPDATED: dirty tree is `.omc` only; preserve artifacts; do not assume unfinished product D-059/D-060 diffs.
2. Wave 02 still mandatory: repo head `003` empty upgrade (no historical backfill); live DB on `002`; no live migrate until Wave 09.
3. ADR-001/002 HOLD-WITH-NOTES: freeze provisional identity; interpret append-only suppress as permanent until reconsider; add `ReconsiderDismissSuppress`.
4. No AI / outreach / private auto-join / Stars.
5. Do not invent new product forks beyond ADRs / D-059 / D-060 / plan §2–§4.

### Current system (contract gaps vs code — for writer context only)

| Gap | Evidence | Wave that implements after freeze |
|---|---|---|
| Provisional identity not in DOMAIN/PRD | Architect W00 ADR-001 | W01 docs → W02 code |
| Suppress entity missing from DOMAIN_MODEL | Grep DOMAIN — no `Dismissed*` | W01 docs → W02 |
| No reconsider-suppress command | SRC commands end at `ReconsiderSource` | W01 → W02/W08 |
| Novelty / pool_exhausted / replacement not MUST | SRC-029/031/032 counters only | W01 → W03 |
| `HistoryRequest.source_id` used as Telethon peer | INTEGRATION_CONTRACTS + W00 | W01 → W05 |
| Runtime loops deferred | INF-002/021 exist; code deferred | W01 extend → W06 |
| SEED_RULES runtime fallback | DET-006 exists; call site gap | W01 sharpen → W07 |
| Weak default UI filter missing | UI-017 no band default | W01 → W08 |
| Plan §2 capacity/calibration vs NFR drift | See Area 10 | W01 NFR align → W09/W07 |

### Root cause or design pressure

Contracts for keyword suppress (D-059/D-060) exist, but remediation needs a **complete identity + acquisition + runtime + pinning + SLO** freeze so Wave 02+ cannot invent thresholds or dual-own entities. Pressure is documentation completeness, not new ADR redesign.

---

## ID allocation (PROPOSED next-free after scan)

| Prefix | Current max (TRACEABILITY / PRD) | First PROPOSED new |
|---|---:|---:|
| `SRC` / `AT-SRC` | 032 | **033** |
| `COL` / `AT-COL` | 022 | **023** |
| `PROC` / `AT-PROC` | 018 | **019** |
| `STO` / `AT-STO` | 016 | **017** |
| `DET` / `AT-DET` | 015 | **016** |
| `SCR` / `AT-SCR` | 016 | (extend SCR-007 only; no new unless needed) |
| `UI` / `AT-UI` | 018 | **019** |
| `OBS` / `AT-OBS` | 018 | **019** |
| `INF` / `AT-INF` | 021 (at least) | **022** |
| `NFR-PERF` | 005 | **006** |
| `NFR-REL` | 007 | **008** |
| `NFR-QLT` | 005 | **006** |
| Decisions | D-060 | **D-061..D-067** (batch remediation freeze) |

Traceability rule: keep **1:1** `REQ ↔ AT` where catalogue already uses that pattern (SRC/COL/STO).

---

## Decision log proposals (writer MUST add; do not reopen D-059/D-060)

| PROPOSED ID | Decision (freeze text) | Modules |
|---|---|---|
| **D-061** | Canonical public source identity = Telegram numeric peer ID after resolve; provisional key `username:<casefold>` until resolve; cannot enter `monitoring`; transactional merge into peer identity preserves dismiss provenance and aliases (ADR-PLAN-001) | `SRC`, `STO`, `COL` |
| **D-062** | Durable dismiss suppress ledger: permanent membership until explicit `ReconsiderDismissSuppress`; retention MUST NOT delete; historical dismissed opportunity snapshots MUST be backfilled idempotently; claim fields MAY upsert; optional audit events append (ADR-PLAN-002 interpretation) | `SRC`, `STO`, `UI` |
| **D-063** | Acquisition ≠ qualification: providers stream with cursor/budget/provenance; after suppress worker continues replacement until run quota or `pool_exhausted` with reason; presented novelty gates per §2 (ADR-PLAN-003) | `SRC`, `UI`, `OBS` |
| **D-064** | `HistoryRequest` / live DTOs carry `TelegramPeerRef` (numeric peer and/or public username); DB `source_id` MUST NEVER be passed as Telethon entity; network I/O outside long SQLite write TX; persist batches ≤ `50` envelopes (ADR-PLAN-005 + COL) | `COL`, `STO` |
| **D-065** | Processing/detection load rules only by pinned `rule_set_version_id` + checksum; `SEED_RULES` bootstrap-only; mismatch = hard permanent error, no hidden fallback (ADR-PLAN-006) | `DET`, `PROC`, `STO` |
| **D-066** | RuntimeCoordinator MUST run named loops: keyword/graph discovery claim, collector job worker, live `iter_updates` consumer, processing claim, notification outbox, startup + periodic reconciliation, health watchdog — each with heartbeat/lease; collector MUST NOT remain permanent `STOPPED/deferred` when credentials and monitoring sources exist (ADR-PLAN-004 + INF) | `INF`, `COL`, `PROC`, `OBS`, `NOT` |
| **D-067** | Remediation calibration / capacity release gates follow plan §2 numerics via `NFR-QLT-006` / `NFR-PERF-006..008` / `NFR-REL-008`; opportunity UI bands remain `promising|review|weak` (D-054) with plan prose `strong|moderate` as aliases only | `shared QUALITY`, `SRC`, `UI`, `DET`, `OBS` |

---

## Contract areas (1–11)

### 1. CanonicalSourceIdentity, aliases, provisional identity, merge semantics

| Field | Value |
|---|---|
| **Owner** | `SRC` (entity + commands); physical schema `STO`; resolve I/O `COL` Gateway |
| **Existing IDs** | SRC-007/008 (merge), SRC-022 (identity order), SRC-031/032 (suppress match order), D-059/D-060 |
| **PROPOSED NEW** | **SRC-033** Canonical identity model; **SRC-034** Provisional identity lifecycle + atomic merge; **AT-SRC-033**, **AT-SRC-034**; decision **D-061** |
| **Entities (single owner SRC)** | Add `CanonicalSourceIdentity` (logical): `canonical_key` ∈ {`peer:<telegram_id>`, `username:<casefold>`}; `telegram_id: int \| null`; `username_normalized: str \| null`; linked `SourceAlias[]`. Do **not** dual-own `SourceAlias` (already SRC). |
| **Events/DTO** | Extend promotion/suppress match to use `canonical_key`; merge emits existing `SourceApprovalEvent` / discovery merge outcomes — no second owner |
| **Thresholds/limits** | Identity order (frozen): `telegram_id` → registry `telegram_id` → current username → `SourceAlias` → provisional `username:<casefold>`. Provisional MUST NOT reach `monitoring`. One canonical key per opportunity snapshot per run (extends SRC-022). |
| **Writer files** | `docs/prd/modules/01-source-discovery/PRD.md`; `docs/prd/shared/DOMAIN_MODEL.md`; `docs/prd/shared/INTEGRATION_CONTRACTS.md` (identity notes); `docs/prd/DECISION_LOG.md` (D-061); `docs/prd/TRACEABILITY.md` |
| **Wave 02+ deps** | Wave 02 implements merge + unique constraints; schema may allow nullable `telegram_id` **or** store provisional only on suppress/opportunity until resolve — choose one representation in PRD, implement in W02 |

**AT sketches (PROPOSED):**
- `AT-SRC-033`: same peer under two usernames → one identity, two aliases.
- `AT-SRC-034`: unresolved username opportunity → provisional key; after resolve merge into peer; dismiss provenance retained; monitoring blocked while provisional.

---

### 2. DismissedSource / suppress ledger, provenance, reconsider, retention immunity

| Field | Value |
|---|---|
| **Owner** | `SRC` (semantics/commands/events); `STO` (table/migration/retention immunity); `UI` (reconsider UX) |
| **Existing IDs** | SRC-026, SRC-030, SRC-032, D-060, STO-016 (keyword retention — **must extend**, not delete suppress) |
| **PROPOSED NEW** | **SRC-035** Suppress ledger entity + provenance fields; **SRC-036** `ReconsiderDismissSuppress` command + audit; **STO-017** Retention immunity + historical backfill invariant for suppress table; **UI-019** Reconsider dismiss-suppress UI with confirmation; **AT-SRC-035/036**, **AT-STO-017**, **AT-UI-019**; decision **D-062** |
| **Entities** | `DismissedSource` / `DismissedKeywordSource` (**SRC** logical owner): `canonical_key`, `telegram_id` nullable, `usernames_json`/`aliases`, `dismiss_reason`, `dismissed_at`, `source_opportunity_id` nullable, `operator_trigger`, `version`/upsert stamp. Audit: append-only `SourceDiscoveryEvent` or dedicated `DismissSuppressEvent` (**SRC**). |
| **Commands** | Existing `DismissOpportunity` (extend). **NEW** `ReconsiderDismissSuppress(canonical_key\|suppress_id, note, CSRF, version)` → removes membership only via explicit action; emits audit event. Distinct from `ReconsiderSource` (`rejected→candidate`). |
| **Thresholds/limits** | Dismissed recurrence across future runs = **0** (plan §2). Historical backfill: every `SourceOpportunitySnapshot.review_state=dismissed` (all ages) MUST yield ≥1 suppress membership row after migrate (idempotent). Retention: suppress rows **never** purged by SRC-030/STO-016 matrix. Re-dismiss idempotent (already SRC-032). |
| **Writer files** | SRC PRD; STO PRD §11 retention table + STO-017; DOMAIN_MODEL entity list; INTEGRATION_CONTRACTS keyword commands; DECISION_LOG D-062; TRACEABILITY; UI PRD |
| **Wave 02+ deps** | Wave 02 migration backfill + tests; Wave 08 UI; Wave 09 live count gates |

**Do not:** treat snapshot `review_state=dismissed` alone as durable suppress (already rejected).

---

### 3. Discovery run novelty counters, suppress counters, pool exhaustion reason

| Field | Value |
|---|---|
| **Owner** | `SRC` (run counters/state); `OBS` (metrics export); `UI` (run detail display) |
| **Existing IDs** | SRC-016 (graph report), SRC-031 (`registry_suppressed`), SRC-032 (`dismissed_suppressed`), OBS-017 |
| **PROPOSED NEW** | **SRC-037** Run funnel counters + novelty ratio; **SRC-038** `pool_exhausted` terminal reason codes; **OBS-019** Novelty/suppress/exhaustion metrics; **UI-020** Run detail shows funnel; **AT-SRC-037/038**, **AT-OBS-019**, **AT-UI-020**; **D-063** |
| **DTO / fields on `DiscoveryRun`** | Counters (all int ≥0): `acquired_total`, `canonicalized_total`, `registry_suppressed`, `dismissed_suppressed`, `duplicate_in_run`, `cooldown_suppressed`, `qualified_total`, `presented_total`, `novel_presented_total`, `replacement_fetches_total`; `pool_exhausted: bool`; `pool_exhausted_reason: enum` (below); `novelty_ratio: float` = `novel_presented_total / max(1, presented_total)` for completed runs. |
| **`pool_exhausted_reason` enum (closed)** | `provider_empty`, `budget_cap_reached`, `quota_skipped_remaining`, `flood_wait_deferred`, `cancel_requested`, `no_unseen_after_suppress` |
| **Thresholds/limits** | Deterministic fixture with sufficient replacement pool: novelty_ratio ≥ **0.80** after first run; dismissed recurrence = **0**. Live pilot: **5** sequential runs; median pairwise Jaccard of presented canonical sets ≤ **0.60** OR each violating run has proven `pool_exhausted=true` with reason (plan §2). |
| **Writer files** | SRC PRD; DOMAIN_MODEL `DiscoveryRun` counters; INTEGRATION_CONTRACTS `KeywordDiscoveryRunFinished` counters; OBS PRD; UI PRD; TRACEABILITY |
| **Wave 02+ deps** | Wave 03 implements; Wave 08 UI; Wave 09 live Jaccard |

---

### 4. Provider cursor / budget / provenance and replacement acquisition

| Field | Value |
|---|---|
| **Owner** | `SRC` (worker semantics); search ports `COL`; persistence cursor `STO` via jobs/run query rows |
| **Existing IDs** | SRC-018..020, SRC-024, SRC-027, SRC-029, COL-021/022, D-050..058 |
| **PROPOSED NEW** | **SRC-039** Acquisition/qualification/presentation stages; **SRC-040** Replacement acquisition after suppress; **SRC-041** Cross-run presentation cooldown; **AT-SRC-039..041** |
| **Stages (machine-readable)** | `acquired` → `canonicalized` → `suppressed` → `qualified` → `presented` (ADR-003). Provenance MUST record provider method ∈ existing discovery methods + `keyword_search`/`linked_discussion`/`recommendation`/`public_link`/`mention`/`forward_origin`. |
| **Thresholds/limits (reuse SRC-029 + freeze cooldown)** | Page size global **50**, max **2** pages/query/scope; evidence cap **500**/run; directory ≤**20** peers/query; deep ≤**25** sources; ≤**5** profile queries/source; ≤**20** messages; window **30** days. **Cooldown (PROPOSED freeze):** already-presented **non-dismissed** canonical identity hidden from default presentation for **24 hours** across keyword runs; permanent dismiss (SRC-032) is **not** replaced by cooldown. Replacement: continue provider cursor until presented quota (deep/qualification caps) OR `pool_exhausted`. |
| **Writer files** | SRC PRD (extend SRC-024 deep selection: use **profile** queries, not global `post_queries[:5]`); INTEGRATION_CONTRACTS search cursor semantics; DECISION_LOG D-063; TRACEABILITY |
| **Wave 02+ deps** | Wave 03; profile field application (`required_service_profiles`, `additional_exclusions`) under SRC-039/024 extension |

---

### 5. Graph edge types and public-only targets

| Field | Value |
|---|---|
| **Owner** | `SRC` (graph run semantics); Gateway methods `COL` |
| **Existing IDs** | SRC-003..006, SRC-009..011, D-017, COL `get_recommendations` / `get_linked_discussion` |
| **PROPOSED NEW** | **SRC-042** Allowed graph edge types + public-only + per-seed edge cap; **AT-SRC-042**. **Do not change** D-017 depth=`2`, candidate_cap=`100`, expansion/resolve cap=`25`. |
| **Edge types (closed, public-only)** | `recommendation`, `public_link`, `mention`, `forward_origin`, `linked_discussion` — already in SRC-003/023. Targets MUST be public `channel|megagroup|group` with resolvable public identity. Private/invite-only/unconfirmed username MUST NOT become candidates (`unsupported_source` / skip). |
| **Thresholds/limits** | max_depth = **2** (D-017 — **supersedes** plan Wave 04 `depth=1`); candidate_cap = **100**; resolve/expansion_cap = **25**; **PROPOSED** max outgoing edges examined per seed node = **25** (align expansion_cap); max unique graph candidates/run = **100**; one canonical node resolved at most once per run; FloodWait → provider phase `retry_wait` / run degraded, state preserved. |
| **Writer files** | SRC PRD §3 + SRC-042; DOMAIN_MODEL depth note; INTEGRATION_CONTRACTS recommendations contract; TRACEABILITY; optional plan soft-note by coordinator (not writer ownership) that Wave 04 `depth=1` → use PRD `2` |
| **Wave 02+ deps** | Wave 04 gateway+service; security-reviewer public boundary |

---

### 6. Eligibility evidence and exact source-quality sampling

| Field | Value |
|---|---|
| **Owner** | `SRC` (opportunity eligibility/score); pure detect reuse `DET-015`; **not** SCR |
| **Existing IDs** | SRC-024, SRC-025, SRC-018 (`required_service_profiles`, `additional_exclusions`), D-054 |
| **PROPOSED NEW** | **SRC-043** Evidence eligibility gates; **SRC-044** Neutral noise sampling; **SRC-045** Profile semantics enforcement; **AT-SRC-043..045** |
| **Rules (numeric / closed)** | Directory-only (no message/member/activity evidence) MUST NOT receive band `review` or `promising` (score forced into `weak` **0–34** or explicit `needs_verification` presentation flag — **PROPOSED:** band stays `weak`, reason code `directory_only_no_evidence`). Linked discussion / source lacking verification evidence → reason `needs_verification`; MUST NOT get `moderate/strong` equivalents (`review`/`promising`) without deep verification. Noise sample: up to **20** messages in **30**-day window, neutral (not only exact-query hits), same caps as SRC-024. `additional_exclusions` apply with explainable reason. `required_service_profiles` affect eligibility/score. |
| **Band mapping (frozen)** | Plan `strong` ≡ `promising` (60–100); plan `moderate` ≡ `review` (35–59); `weak` (0–34). **Do not rename enums.** |
| **UI default quality** | Default candidate queue shows bands **`promising,review` only**; `weak` only via explicit filter (plan §2) — see Area 11 / UI-021. |
| **Writer files** | SRC PRD; DOMAIN_MODEL opportunity reason codes; UI PRD; TRACEABILITY |
| **Wave 02+ deps** | Wave 03 qualification; Wave 08 default filter |

**Note:** `TelegramSource.quality_score` (0..5) remains separate (D-054). Monitoring source-quality sampling for SCR inputs is out of this SRC opportunity scope unless already defined elsewhere — do not conflate.

---

### 7. Telegram peer reference, backfill cursor/continuation, live update DTO

| Field | Value |
|---|---|
| **Owner** | `COL` (Gateway + collector jobs/checkpoints/envelopes); consumers `PROC`, `SRC` (resolve only) |
| **Existing IDs** | COL-002, COL-005..010, COL-013..020, D-039, D-040 |
| **PROPOSED NEW** | **COL-023** `TelegramPeerRef` mandatory for Telegram I/O; **COL-024** Backfill continuation beyond single page; **COL-025** Persist batching / no network inside long write TX; **COL-026** Live `TelegramUpdateDTO` contract completeness; **AT-COL-023..026**; **D-064** |
| **DTO changes (COL owns)** | `TelegramPeerRef`: `schema_version=1`, `telegram_peer_id: int \| null`, `access_hash: int \| null`, `username_normalized: str \| null` — at least one of peer_id or username required. `HistoryRequest`: replace bare DB-peer misuse — fields `source_id` (DB FK for jobs) **plus** `peer: TelegramPeerRef`; `after_message_id`, `after_published_at`, `before_published_at`, `limit`, `purpose`, `continuation_cursor` opaque. Gateway MUST use `peer`, never raw DB `source_id`, as Telethon entity. `TelegramUpdateDTO` / envelope: stable identity `(telegram_peer_id, telegram_message_id)`; event_type `message_new\|message_edited\|message_deleted`; maps to monitoring `source_id` via registry. |
| **Thresholds/limits** | Initial backfill: **14 days** OR **3000** messages, whichever first (COL-005) — **not** hard-coded 100. Startup reconciliation batch ≤**5000**; periodic every **15 min**, ≤**1000**/source/batch; continuation job when cap hit. Persist batch size ≤ **50** envelopes per SQLite write TX. Job lease **5 min**, heartbeat **60 s** (COL-019). FloodWait exact `until`. Live filter: only `lifecycle_state=monitoring`. |
| **Writer files** | COL PRD; INTEGRATION_CONTRACTS §2 (`HistoryRequest`, peer ref, update DTO); DOMAIN_MODEL envelope notes; TRACEABILITY; DECISION_LOG D-064 |
| **Wave 02+ deps** | Wave 05 implementation; Wave 06 loops; Wave 09 load — **must not** expand live monitoring pilot before COL-023 verified |

---

### 8. Job types / states / lease / idempotency / reconciliation schedule

| Field | Value |
|---|---|
| **Owner** | Physical `Job` table `STO`; type semantics: `COL` collection jobs, `SRC` discovery jobs, `PROC` processing, `NOT` outbox (separate), `INF` orchestration |
| **Existing IDs** | COL-004, COL-007/008, COL-015..019, STO-006, PROC-001/016/017, OBS-011, INF-002/003/021, DOMAIN `Job.job_type` |
| **PROPOSED NEW** | **STO-018** Unified job lease/idempotency invariants (cross-type); **INF-022** Named runtime loops + reconciliation schedule wiring; **OBS-020** Loop health (not permanent deferred); **AT-STO-018**, **AT-INF-022**, **AT-OBS-020**; **D-066** |
| **Job types (closed — extend DOMAIN enum if missing)** | Keep: `discovery`, `keyword_discovery`, `initial_backfill`, `startup_reconciliation`, `periodic_reconciliation`, `continuation`, `process_message`, `replay_message`, `rescore`, `purge`, `backup`. States: `queued`, `running`, `retry_wait`, `succeeded`, `failed`, `dead`, `cancelled` (+ keyword run-level states on `DiscoveryRun`, not Job). |
| **Thresholds/limits** | Lease **5 minutes**; heartbeat every **60 s**; expired lease → `running→queued` on startup/scan. Transient retries **5** with delays **1, 5, 30, 120, 600** s (COL/PROC). Periodic reconciliation every **15 minutes**. Idempotency: unique inbox/envelope keys; unique outbox key; one unfinished job per `(source_id, type)` for collector activation (COL-004). Startup reconciliation after connect + live start. |
| **Writer files** | DOMAIN_MODEL `Job`; STO PRD; INF PRD INF-022; OBS PRD; COL/PROC cross-links; TRACEABILITY; DECISION_LOG D-066 |
| **Wave 02+ deps** | Wave 06 runtime; do not claim PASS on health if collector `deferred` while monitoring sources exist |

---

### 9. Rule-set loader / version / checksum pinning

| Field | Value |
|---|---|
| **Owner** | `DET` (catalog/loader/activation); binding at process time `PROC`; storage `STO`; scouting pin already D-055/SRC-018 |
| **Existing IDs** | DET-001, DET-006, DET-011, DET-015, PROC-015, SCR-007, D-055 |
| **PROPOSED NEW** | **DET-016** Runtime loader by version+checksum; bootstrap-only seed; **PROC-019** Processing job MUST pass pinned version+checksum into detect; **AT-DET-016**, **AT-PROC-019**; **D-065** |
| **Rules** | Loader fetches immutable compiled catalog from DB/cache keyed by **checksum**. Missing version or checksum mismatch → permanent processing error / dead-letter (`RULE_SET_INVALID` / equivalent) — **no** `SEED_RULES` silent fallback. `SEED_RULES` allowed **only** when creating initial DB version at bootstrap/migration. Re-score creates new `ProcessingResult` / score trace; does not rewrite historical detection rows. |
| **Thresholds/limits** | Regex timeout **50 ms**; input cap **4096** chars (stack); compile cache key = checksum; byte-stable result for same revision+version (NFR-QLT-005). |
| **Writer files** | DET PRD; PROC PRD; INTEGRATION_CONTRACTS detection; DECISION_LOG D-065; TRACEABILITY |
| **Wave 02+ deps** | Wave 07; edge `W01→W07` remains valid |

---

### 10. Performance / latency / recovery / product-quality metrics (plan §2)

| Field | Value |
|---|---|
| **Owner** | Shared `QUALITY_REQUIREMENTS.md` (`NFR-*`); product discovery metrics `SRC`/`OBS`; capacity harness evidence Wave 09 |
| **Existing IDs** | NFR-PERF-001..005, NFR-REL-001..007, NFR-QLT-001..005, NFR-SEC-001..006, OBS-017 |
| **PROPOSED NEW** | **NFR-PERF-006** Monitoring capacity 100 sources / ≥1000 msg/day ingestion; **NFR-PERF-007** Burst 10 msg/s × 10 min, drain ≤15 min; **NFR-PERF-008** p95 `received_at→processed_at` ≤30 s steady / ≤120 s burst; **NFR-REL-008** Kill/restart reconciliation continues from checkpoint without gap/dup; **NFR-QLT-006** Remediation calibration gates (align plan §2); **OBS-021** Capacity/latency/recovery metric names; acceptance ATs mirrored in QUALITY_REQUIREMENTS tables |

**Concrete thresholds to freeze (plan §2 — authoritative for remediation release):**

| Gate | Number |
|---|---|
| Permanent suppress recurrence | **0** |
| In-run canonical dedupe | ≤ **1** presentation / canonical / run |
| Novelty (sufficient pool) | ≥ **80%** novel presented after first run |
| Live 5-run Jaccard | median pairwise ≤ **0.60** or proven `pool_exhausted` |
| Monitoring sources | **100** |
| Steady ingestion | ≥ **1000** messages/day (harness); external volume reported separately |
| Burst | **10**/s for **10** min = **6000** events; backlog drain ≤ **15** min |
| Exact dedupe | **100%** (0 duplicate raw/lead/outbox on replay) |
| p95 received→processed | ≤ **30** s steady; ≤ **120** s burst |
| Recovery | resume jobs + checkpoint; no gap; restart recovery wall ≤ **5** min (align NFR-REL-004) |
| Calibration corpus | ≥ **500** messages from ≥ **10** source types |
| Hot precision | ≥ **0.80** |
| Hot+warm precision | ≥ **0.70** |
| Purchase-intent recall | ≥ **0.75** |
| UI bind | `127.0.0.1` only |

**NFR drift resolution (writer MUST document in DECISION_LOG / QUALITY_REQUIREMENTS):**

| Existing | Plan §2 | Freeze rule |
|---|---|---|
| NFR-PERF-001: p95 live→**Lead** ≤10 s @ burst | p95 received→**processed** ≤30/120 s | **Keep both** — different endpoints; add NFR-PERF-008 for processed path |
| NFR-QLT-002: hot+warm precision ≥**80%** | hot+warm ≥**70%**, hot ≥**80%** | **D-067 PROPOSED:** remediation release uses plan §2 (**NFR-QLT-006**); update NFR-QLT-002 text to “superseded for remediation by NFR-QLT-006” **or** amend NFR-QLT-002 to hot≥80% and hot+warm≥70% in the same edit — **one numeric source of truth required** |
| NFR-QLT-003: recall `direct_order` ≥70% | purchase-intent recall ≥75% | Map `purchase-intent` ≡ DET category/`direct_order` (or named profile); freeze recall ≥ **0.75** under NFR-QLT-006 |

| **Writer files** | `docs/prd/shared/QUALITY_REQUIREMENTS.md`; DECISION_LOG; OBS PRD; TRACEABILITY §3; optional SRC/COL cross-refs |
| **Wave 02+ deps** | Wave 07 calibration; Wave 09 harness — capacity claims invalid until then |

Add **D-067** if needed solely for NFR-QLT alignment (still not a product fork — documentation consistency).

---

### 11. UI defaults and operator lifecycle

| Field | Value |
|---|---|
| **Owner** | `UI` (routes/templates); commands owned by `SRC` / lead modules |
| **Existing IDs** | UI-017/018, SRC lifecycle §4, SRC-012, SRC-026, SET loopback, SEC CSRF |
| **PROPOSED NEW** | **UI-021** Discovery default band filter `promising,review`; **UI-022** Source/opportunity card fields (identity, aliases, provenance, evidence, components, reasons); **UI-023** Lifecycle actions including reconsider-suppress; **UI-024** Monitoring coverage page signals (checkpoint/backlog/errors for up to 100 sources); **AT-UI-021..024** |
| **Lifecycle (frozen existing + extension)** | Source: `candidate→approved→monitoring`; `reject`/`ReconsiderSource`; `pause`/`resume`; `disable`. Opportunity: `promote` / `dismiss` / **`ReconsiderDismissSuppress`**. No auto-approve; no send-to-author; no Stars controls. |
| **Thresholds/limits** | Inbox pagination ≤ **100** leads/request (UI existing). Discovery HTMX poll every **5** s (existing). Default bands: **promising,review**. Weak opt-in only. Bind **127.0.0.1:8765**. CSRF on all state-changing routes. |
| **Writer files** | UI PRD; SRC command table cross-link; INTEGRATION_CONTRACTS; TRACEABILITY |
| **Wave 02+ deps** | Wave 08; depends on W02 suppress reconsider + W03 reasons |

---

## Entity ownership matrix (no dual owners)

| Entity / contract | Owner | Consumers |
|---|---|---|
| `CanonicalSourceIdentity` / provisional key | **SRC** | STO, COL, UI |
| `SourceAlias`, `TelegramSource` lifecycle | **SRC** | COL, UI, STO |
| `DismissedSource` suppress ledger | **SRC** | STO, UI, OBS |
| `DiscoveryRun` counters / pool_exhausted | **SRC** | UI, OBS, STO |
| Provider cursors / Search* DTOs | **COL** (ports); **SRC** (usage semantics) | SRC |
| Graph edge outcomes | **SRC** | COL, UI |
| Opportunity score / bands / eligibility | **SRC** | UI, DET (pure detect only) |
| `TelegramPeerRef`, `HistoryRequest`, `TelegramUpdateDTO` | **COL** | PROC, STO |
| `CollectorCheckpoint`, collection jobs | **COL** | STO, OBS |
| Physical `Job` rows / lease storage | **STO** | COL, SRC, PROC, INF, OBS |
| `RuleSetVersion` + loader | **DET** | PROC, SRC, SCR, STO |
| Processing pin call site | **PROC** | DET |
| NFR / capacity gates | **shared QUALITY** | all; OBS publishes |
| UI defaults / routes | **UI** | SRC/COL ports |
| Runtime loop orchestration | **INF** | COL, PROC, NOT, OBS, SRC |
| Lead score bands hot/warm/cold | **SCR** (unchanged) | UI, NOT — **do not** mix with SRC opportunity bands |

---

## Options considered (Area-level)

| Option | Benefits | Costs/Risks | Best fit |
|---|---|---|---|
| A. Freeze ADR/plan into new MUST/AT (this map) | Unblocks W02+; no open numbers; single owners | Large writer doc edit | **Selected** |
| B. Reopen D-059/D-060 / rename bands to moderate/strong | Matches plan prose literally | Breaks D-054 / existing tests | Rejected |
| C. Skip Wave 02 because `003` exists | Faster | Failure 1 / Critic binding | Rejected |
| D. Adopt plan Wave 04 depth=1 over D-017 | Smaller crawl | Conflicts D-017; plan says use PRD if differs | Rejected — keep depth **2** |

### Recommendation

1. Writer implements this delta in the edit sequence below — Impact: contract freeze gate — Effort: medium (docs only).
2. Critic reviews semantic consistency (bands mapping, NFR-QLT alignment, suppress reconsider vs ReconsiderSource).
3. Verifier runs `uv run python tools/quality/validate-prd.py` + ID/link checks.
4. Do not start Wave 02 product code until Wave 01 verifier PASS.

### Migration and verification (docs wave)

- **Rollout:** docs-only; no Alembic in W01; W02 owns schema/backfill after freeze.
- **Rollback:** revert PRD commits / restore docs from git; no live DB impact.
- **Evidence to collect:** validate-prd exit 0; unique IDs; every new MUST has AT; TRACEABILITY rows; Critic PASS.

---

## Writer checklist (ordered edit sequence)

1. **`docs/prd/DECISION_LOG.md`** — add D-061..D-067; do not alter D-059/D-060 meaning.
2. **`docs/prd/shared/DOMAIN_MODEL.md`** — add `CanonicalSourceIdentity` / `DismissedSource`; extend `DiscoveryRun` counters; `TelegramPeerRef`; Job notes; entity ownership table.
3. **`docs/prd/shared/INTEGRATION_CONTRACTS.md`** — `HistoryRequest`+peer; update DTOs; keyword commands `ReconsiderDismissSuppress`; run finished counters; detection pin note.
4. **`docs/prd/shared/QUALITY_REQUIREMENTS.md`** — add NFR-PERF-006..008, NFR-REL-008, NFR-QLT-006 (+ resolve QLT-002/003 drift).
5. **`docs/prd/modules/01-source-discovery/PRD.md`** — SRC-033..045; commands; AT-SRC-*; band mapping note; graph SRC-042; extend §3 limits only where additive.
6. **`docs/prd/modules/02-telegram-collector/PRD.md`** — COL-023..026; AT-COL-*; backfill caps restated; peer invariant.
7. **`docs/prd/modules/03-message-processing/PRD.md`** — PROC-019 + AT-PROC-019.
8. **`docs/prd/modules/04-lead-detection/PRD.md`** — DET-016 + AT-DET-016; bootstrap-only seed.
9. **`docs/prd/modules/06-lead-storage/PRD.md`** — STO-017/018; retention immunity; AT-STO-*; mention migration 003 backfill invariant (semantics; code in W02).
10. **`docs/prd/modules/07-lead-dashboard/PRD.md`** — UI-019..024 + ATs.
11. **`docs/prd/modules/10-administration-observability/PRD.md`** — OBS-019..021 + ATs.
12. **`docs/prd/modules/12-deployment-infrastructure/PRD.md`** — INF-022 + AT-INF-022 (named loops).
13. **Skim-only consumers if wording touches them:** `05-lead-scoring` (SCR-007 cross-ref only), `08-notifications` (no AI/outreach), `09-operator-settings`, `11-security` (loopback/redaction unchanged).
14. **`docs/prd/TRACEABILITY.md`** — extend module ranges; new section “Remediation contract freeze (D-061+)”; 1:1 AT links.
15. Run (verifier owns, writer may smoke): `uv run python tools/quality/validate-prd.py`.

**Forbidden for writer:** any `src/**`, migrations, tests product behavior, live DB, weakening HC-6, inventing AI/private-join.

---

## AC mapping (this architect deliverable)

| AC | Result |
|---|---|
| 1. All 11 contract areas covered with owner + IDs + files | **PASS** — sections 1–11 |
| 2. No entity has two owners | **PASS** — ownership matrix |
| 3. No open thresholds (all numeric) | **PASS** — cooldown **24h** and persist batch **50** explicitly frozen; graph depth kept **2**; NFR drift resolved via D-067/NFR-QLT-006 rule |
| 4. Clear writer checklist ordered by edit sequence | **PASS** — checklist § above |
| 5. Write `architect-contract-delta.md` | **PASS** — this file |

---

## Return schema

```text
Status: PASS
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-01/architect-contract-delta.md]
AC mapping:
  - AC1 PASS (11 areas)
  - AC2 PASS (single owners)
  - AC3 PASS (numeric thresholds)
  - AC4 PASS (writer checklist)
  - AC5 PASS (this evidence file)
Risks:
  - R-W01-1: Writer renames bands to moderate/strong → breaks D-054 (mitigate: mapping note mandatory)
  - R-W01-2: Writer treats Wave 02 as optional because 003 exists (mitigate: Critic binding + STO-017 backfill MUST)
  - R-W01-3: NFR-QLT-002 vs plan §2 left dual-valued (mitigate: D-067 / NFR-QLT-006 single source)
  - R-W01-4: Cooldown 24h challenged by Critic (mitigate: only numeric underspec in plan Wave 03; escalate REVISE if rejected — do not leave open)
  - R-W01-5: HistoryRequest still documents source_id alone → W05 peer bug recurs (mitigate: COL-023 + D-064)
Remaining gaps:
  - Critic Wave 01 semantic review not yet run
  - Verifier validate-prd not yet run for new IDs
  - Coordinator soft-sync of plan Wave 04 depth=1 prose (optional; PRD depth=2 governs)
Writer handoff: ready
```

### References

- Plan Wave 01 contract list + §2 gates + ADR-PLAN-001..006 — Cursor plan file
- Wave 00 architect HOLD-WITH-NOTES ADR-001/002 — `.omc/artifacts/.../wave-00/architect-report.md`
- Wave 00 critic APPROVE binding notes — `wave-00/critic-report.md`
- D-059/D-060 — `docs/prd/DECISION_LOG.md`
- SRC-022/031/032, bands, limits — `docs/prd/modules/01-source-discovery/PRD.md`
- COL backfill/live/jobs — `docs/prd/modules/02-telegram-collector/PRD.md`
- HistoryRequest — `docs/prd/shared/INTEGRATION_CONTRACTS.md:66-72`
- TRACEABILITY ranges SRC-001..032 — `docs/prd/TRACEABILITY.md`
- NFR tables — `docs/prd/shared/QUALITY_REQUIREMENTS.md`
