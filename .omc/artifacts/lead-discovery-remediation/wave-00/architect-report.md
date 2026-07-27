# Wave 00 — architect ADR steelman / migration–recovery–performance review

- **Agent:** architect (read-only product/docs; evidence write only)
- **Captured_at:** 2026-07-27 (session Wave 00)
- **Plan audited:** `~/.cursor/plans/telegram-lead-discovery-remediation_7067172d.plan.md` §2, §4 ADRs, §8–9 waves, HC-*
- **Inputs:** explorer-report.md (**PASS**), planner-report.md (**PASS**, P-SEQ-01..05)
- **Repo HEAD:** `f1b9445` on `main`
- **Status:** **PASS** (ADRs ratified; no MVP scope break; Critic may APPROVE with binding notes)

---

## Architecture Analysis

### Summary

ADR-PLAN-001..006 remain the correct design targets for remediation. None require **REVISE**. Two need **HOLD-WITH-NOTES** (identity provisional key wording; suppress “append-only” vs current upsert row + missing historical backfill). Wave graph stays valid; Wave 02 is still mandatory despite committed `003` (empty table, no historical backfill, live DB on `002`). Unresolved product decisions: **none** (Wave 01 freezes remaining MUST/AT from already-accepted ADRs/D-059/D-060). Critic recommendation: **APPROVE-ready** with mandatory UPDATED facts and P-SEQ-01..05.

### Current system (evidence)

| Boundary | State | Evidence |
|---|---|---|
| Dirty worktree | Only `.omc` orchestration artifacts | Fresh `git status`: `M .omc/plans/...`, `?? .omc/artifacts/`; product `src/tests/docs` clean (explorer §1 + this session) |
| Suppress schema | Head `003` in repo; live DB still `002`; live table absent | Explorer §4; `003_dismissed_keyword_suppress.py` |
| Suppress semantics | Upsert by `source_telegram_id`; identity helpers exist; **no** historical backfill SQL | `promotion.py:71-113`; `003.upgrade():61-65` returns after create |
| Retention vs suppress | Purge does **not** touch `dismissed_keyword_sources` today | `retention.py:314-341` |
| Runtime | Only keyword discovery claim loop; collector `STOPPED/deferred` | `runtime.py:130-131`, `:232` |
| Gateway stubs | Empty `iter_updates`, empty recommendations; history uses DB `source_id` as Telethon entity | `telethon_gateway.py:109-148` |
| Backfill | Hard limit 100; fetch+persist in one job session | `collector/service.py:109-152`, `:198-204` |
| Detection | Runtime calls `detect()` → `SEED_RULES` | `pipeline.py:230`; `engine.py:98-100` |
| Decisions already logged | D-059/D-060, SRC-031/032 | `DECISION_LOG.md`; SRC PRD |

### Root cause or design pressure

The product gap is **not** wrong ADRs. Pressure comes from (1) partial suppress implementation that looks “done” while live data and historical dismisses are unprotected, (2) services that exist only under direct test calls while coordinator loops are deferred, and (3) SQLite/Telegram I/O boundaries that will fail capacity gates if Wave 05/06 skip ADR-005/004.

---

## 1. ADR steelman (AC1)

### ADR-PLAN-001 — canonical Telegram source identity

**Verdict: HOLD-WITH-NOTES**

**Steelman:** Numeric peer ID as primary public identity, username/aliases as mutable claims, and transactional merge after resolve is the only MVP-safe way to make suppress/dedupe survive rename and multi-provider hits. Matches SRC-022 and existing helpers (`ResolvedSourceIdentity`, `DismissedKeywordSourceIndex` by tid/username/alias in `keyword_search.py`).

**Code alignment:**

- **Confirmed partial:** SRC-022 order used in promote/find (`promotion.py:122-151`); dismiss match by tid/username/alias (`keyword_search.py:160+`).
- **Gap:** Schema forces `source_telegram_id` NOT NULL (`models.py:373`); no provisional key `username:<casefolded>` materialized. Opportunities/dismiss path assume a numeric id already exists.
- **Gap (Wave 05, validates ADR):** `HistoryRequest.source_id` is passed to Telethon as `entity` (`telethon_gateway.py:121-125`) — DB PK ≠ Telegram peer.

**Notes (not REVISE):**

1. Wave 01 MUST freeze provisional identity lifecycle: when it may exist, that it cannot enter `monitoring`, and how merge into numeric peer is atomic (ADR text already decides this; document as MUST/AT).
2. Do not treat current helper coverage as Wave 02 completion (P-SEQ-05).

**Counterargument rejected:** Username-only identity — fails rename/alias; already rejected in plan §4.

---

### ADR-PLAN-002 — append-only suppress ledger

**Verdict: HOLD-WITH-NOTES**

**Steelman:** Durable suppress independent of opportunity snapshot retention is required by D-060/SRC-032 and by live evidence (10 dismissed opportunities; purge deletes unpromoted snapshots — `retention.py:201+` / explorer F10). Discovery must not self-unsuppress.

**Code alignment:**

- **Confirmed:** Table + model + upsert on dismiss (`003_*`, `DismissedKeywordSource`, `promotion._upsert_dismissed_suppress_rule`); retention currently immune (no purge of suppress table).
- **Gap (Failure 1 live):** `003.upgrade()` creates empty table and returns — **no** INSERT from historical `review_state=dismissed` snapshots (`003:61-65`).
- **Gap:** Live DB still on `002` → table absent → SRC-032 cannot hold on operator data until Wave 09 migrate after Wave 02 semantics.
- **Semantic note:** Implementation is **upsert mutable row** (update aliases/reason), not an immutable event log. SRC-032 already requires idempotent re-dismiss. ADR “append-only” should be interpreted in Wave 01 as: **suppress membership is permanent until explicit reconsider; rows are not deleted by retention/retry; optional audit events may append; claim fields may update.**

**Notes (not REVISE):**

1. Wave 02 owns historical backfill + temp `002→003` proofs; live apply remains Wave 09 Part B (P-SEQ-02/03).
2. Wave 01 must add `ReconsiderDismissSuppress` (or equivalent) command — SRC-012 has `ReconsiderSource` for lifecycle, but SRC-032 command table has no suppress reconsider yet (PRD commands list ends at `ReconsiderSource` for sources). ADR already decides: separate auditable action; not an open product fork.
3. Downgrade drops table (`003.downgrade`) — **not** primary live recovery; backup+restore remains the recovery path (plan Wave 02/09).

**Counterargument rejected:** Snapshot `review_state=dismissed` alone — fails after retention purge and new runs.

---

### ADR-PLAN-003 — acquisition separated from qualification

**Verdict: HOLD**

**Steelman:** Early fixed top-N after suppress empties the presented set and locks directory recurrence. Separating provider stream → canonicalize/suppress → replacement → qualify → present is the only path to novelty ≥80% and `pool_exhausted` honesty without raising API cost via blind top-N inflation.

**Code alignment:**

- Search cursors exist for pages (`worker.py` cursor helpers), but deep verification still uses global `post_queries[:DEEP_QUERIES_PER_SOURCE]` (explorer F6; `worker.py:873-910`).
- Profile fields stored, not applied in qualification (explorer F7).
- Live opportunities all `weak`/score 0 (explorer F10).

**Wave ownership:** Wave 03 (+ graph pool Wave 04). No ADR change.

**Counterargument rejected:** Raise opportunity score on directory-only — rejected in plan §4; masks missing evidence.

---

### ADR-PLAN-004 — one runtime coordinator, several explicit loops

**Verdict: HOLD**

**Steelman:** Unit/integration coverage of services does not equal production ingestion. One process, one Telethon session owner, multiple named loops with health/heartbeat/lease is required by single-process MVP and observability.

**Code alignment:**

- `RuntimeCoordinator` starts only `KeywordDiscoveryClaimLoop` (`runtime.py:130-131`).
- Collector health forced `STOPPED`/`deferred` (`runtime.py:232`); docstring admits collector worker “(later)” (`:51`).
- `handle_backfill_job` / `process_next_envelope` / outbox workers: callers are tests only (explorer §3).

**Wave ownership:** Wave 06 (after gateway correctness Wave 05). No ADR change.

**Counterargument rejected:** One infinite coroutine without job states — unrecoverable and unobservable.

---

### ADR-PLAN-005 — network I/O outside long SQLite transaction

**Verdict: HOLD**

**Steelman:** WAL + `busy_timeout=5000` (`db.py:24-25`) cannot save UI/writer latency if Telethon iteration holds an open write transaction across many messages. Bounded fetch → claim/persist batches → checkpoint after durable commit is required for burst/recovery SLOs.

**Code alignment:**

- **Good pattern:** `approve_source` commits before `validate_source` (`service.py:218-221`).
- **Violation:** `handle_backfill_job` iterates `gateway.iter_history` while flushing envelopes/checkpoints in the same session (`collector/service.py:132-140`). Same for reconciliation (`:174-180`).

**Wave ownership:** Wave 05 implementation; Wave 09 proves under load. No ADR change.

**Counterargument rejected:** Larger single transaction for “atomicity” — conflicts with UI responsiveness and crash mid-fetch recovery.

---

### ADR-PLAN-006 — rule-set loaded by pinned version

**Verdict: HOLD**

**Steelman:** Storage already models `rule_set_versions` / checksum / detection uniqueness (`models.py` rule tables). Runtime `SEED_RULES` fallback destroys reproducibility and calibration gates.

**Code alignment:**

- `detect(... rules=None)` → `SEED_RULES` (`engine.py:98-100`).
- `process_envelope` calls `detect(norms.analysis_text)` with no version (`pipeline.py:230`).
- Discovery runs already store `rule_set_version_id` / checksum fields on models — pinning is incomplete at call site.

**Wave ownership:** Wave 07 after Wave 01 contract freeze (`W01→W07`). No ADR change.

**Counterargument rejected:** Keep seed fallback when DB version present — rejected in plan §4.

---

### ADR alternatives table (plan §4) — architect confirmation

All listed forbidden alternatives remain correctly rejected. No revival. Out-of-MVP (AI ranking, private auto-join, Stars) → stop condition **not** triggered.

---

## 2. Migration / recovery review (AC2)

### Wave 02 (temp DB only) — `003` + historical backfill

| Topic | Assessment |
|---|---|
| Repo head | Already `003_dismissed_keyword_suppress` (single head) |
| What Wave 02 is **not** | “Add untracked migration file” (STALE HC-5) |
| What Wave 02 **is** | Complete ledger semantics: historical dismiss backfill, alias/provisional merge tests, reconsider path, retention immunity assertion, fix stale head assert `test_storage_settings.py:51-53`, idempotent re-migrate |
| Empty upgrade risk | **High** — green `upgrade()` without rows ⇒ false confidence (planner R-00-3 / Failure 1) |
| Historical source | Live aggregates: 10 dismissed opportunities (explorer §5). Backfill MUST read dismissed snapshots (and any other agreed provenance) into `dismissed_keyword_sources` idempotently |
| Unique key | `uq_dismissed_keyword_source_telegram_id` — sufficient for numeric peer; provisional username-only suppress needs Wave 01 schema decision if provisional keys are in scope before resolve |
| Rollback | Temp DB: reverse migration or recreate. Live: **backup + restore**, not in-place downgrade while runtime up |

### Wave 09 live pilot risks

| Risk | Why | Mitigation already in plan |
|---|---|---|
| Live still on `002` | Any early `tld migrate` against `%LOCALAPPDATA%` violates HC-6 | P-SEQ-03; Part B checklist: stop → integrity → backup → copy dry-run → apply |
| Historical count mismatch | After migrate, suppress rows ≪ dismissed snapshots | Dry-run count gates before/after |
| Peer misuse in live backfill | `iter_history` uses DB id as entity | **Must not** expand monitoring pilot until Wave 05 peer fix verified |
| Process lock / dual process | Second `tld run` or migrate under load | Stop runtime; confirm lock released |
| FloodWait during stepped 5→100 | Single session; no account rotation (by design) | Bounded retry; health degraded; do not bypass limits |
| False health | Discovery loop healthy while collector deferred | Wave 06 must clear permanent `deferred`; pilot gate checks envelopes/jobs age |
| Capacity vs external volume | External chats may not emit 1000 msgs/day | Harness proves ingestion; UI shows observed volume separately (§2 out-of-scope note) |

---

## 3. Performance notes vs capacity gates (AC3)

Target gates (§2): 100 monitoring sources; ≥1000 msg/day steady; burst 10 msg/s × 10 min; drain ≤15 min; p95 latency ≤30 s steady / ≤120 s burst; exact dedupe 100%; restart without duplicate raw/lead/outbox.

| Gate pressure | Current stub/gap | Implication |
|---|---|---|
| Throughput | No collector/processing/outbox loops | Capacity **unmeasurable** until Wave 06 E2E |
| Backfill coverage | `limit: 100`, no continuation | Even one active source cannot meet historical depth; Wave 05 |
| Writer contention | History I/O inside write session | Under burst, expect `database is locked` / UI stall — ADR-005 mandatory |
| SQLite config | WAL + busy_timeout=5000 present | Necessary but insufficient without batching |
| Fan-out 100 sources | Live: 1 monitoring + 1 queued backfill never claimed | Coordinator must schedule fair claim without holding TX across Telethon |
| Detection cost | Full `SEED_RULES` scan per message; no pin/cache key by checksum | Wave 07 compile cache by checksum; regex timeout already domain rule |
| Load harness | Not present | Wave 09 Part A owns deterministic generator; do not claim capacity from unit tests |

**Architect constraint for executors:** Prefer small persist batches (order tens of messages) with checkpoint after commit; never enlarge backfill TX to “finish faster.”

---

## 4. Unresolved product decisions (AC4)

**Empty.** No open product fork blocking Wave 01.

| Candidate | Disposition |
|---|---|
| Provisional identity / reconsider suppress / novelty thresholds / graph budgets | Already decided in ADR-PLAN-* + plan §2/§4 or D-059/D-060; Wave 01 **documents** MUST/AT — does not reopen |
| AI / private join / Stars / outreach | Explicitly out of scope → not decisions |
| Live migrate now | Ops forbidden until Wave 09 — not a product ambiguity |

If Critic finds a true requirement conflict (e.g. provisional key vs NOT NULL telegram_id without schema plan), escalate to **BLOCKED** — none found in this review.

---

## 5. Sequencing / planner ratification

- Wave graph **valid**; **no reorder / merge / new wave**.
- Adopt planner **P-SEQ-01..05** as binding coordinator notes (HC-5 UPDATED; Wave 02 = semantics+backfill not “add file”; forbid live migrate; do not skip Wave 02).
- Wave 01 product-decision blockers: **none**.

---

## 6. Recommendation to Critic (AC5)

**APPROVE-ready**

Mandatory notes Critic must treat as binding (wording/ops, not ADR redesign):

1. HC-5 / §3 F8 STALE → UPDATED per explorer+planner.
2. P-SEQ-01..05.
3. ADR-001/002 HOLD-WITH-NOTES clarifications for Wave 01 writer (provisional identity freeze; suppress durability semantics vs upsert row; historical backfill invariant).
4. Do not skip Wave 02.
5. Capacity gates deferred to Wave 09 evidence; current stubs make early PASS claims invalid.

**REVISE required only if** Critic rejects UPDATED facts or demands ADR redesign — architect does **not** require ADR REVISE list.

---

## 7. Risk register deltas (architect)

| ID | Risk | Severity | Owner |
|---|---|---|---|
| R-A-01 | “003 committed” misread as suppress complete | High | Wave 02 + Critic |
| R-A-02 | Upsert row without historical backfill ⇒ dismissed recurrence after retention | High | Wave 02 |
| R-A-03 | Live pilot before peer-id fix corrupts/ misses history | Critical | Wave 05 gate before Wave 09 scale-up |
| R-A-04 | Permanent `collector=deferred` masked by healthy discovery | High | Wave 06 |
| R-A-05 | Burst + in-TX Telethon → SQLite lock / missed latency SLO | High | Waves 05/09 |
| R-A-06 | SEED_RULES fallback invalidates calibration claims | High | Wave 07 |
| R-A-07 | Citing 158/1 or Ruff without Wave 00 verifier | Med | Wave 00 verifier |

---

## 8. AC mapping

| AC | Result | Evidence |
|---|---|---|
| 1. ADR-PLAN-001..006 HOLD / HOLD-WITH-NOTES / REVISE | **PASS** | §1 — 001/002 HOLD-WITH-NOTES; 003–006 HOLD; zero REVISE |
| 2. Migration/recovery Wave 02 + Wave 09 | **PASS** | §2 |
| 3. Performance vs capacity gates | **PASS** | §3 |
| 4. Unresolved product decisions empty or BLOCKED | **PASS** — empty | §4 |
| 5. Critic recommendation | **PASS** — APPROVE-ready | §6 |
| 6. Write `architect-report.md` | **PASS** | this file |

---

## 9. Remaining gaps (not architect ownership)

- Fresh pytest / ruff / validate-prd exit codes → Wave 00 verifier.
- Exact Jaccard across last 5 runs → optional.
- Deep Telethon peer/access-hash design → Wave 05 architect slice.
- Critic independent verdict.

---

## Return schema (for coordinator)

```text
Status: PASS
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-00/architect-report.md]
Commands:
  - MCP sequentialthinking (3 thoughts) → ok
  - Read plan, explorer, planner, skills, cited modules
  - Grep: dismiss/suppress/identity/reconsider/SEED_RULES/runtime
  - user-git git_status → M .omc/plans/...; ?? .omc/artifacts/
AC mapping:
  - AC1 PASS (001/002 HOLD-WITH-NOTES; 003-006 HOLD)
  - AC2 PASS (Wave 02 backfill + Wave 09 pilot risks)
  - AC3 PASS (capacity vs stubs)
  - AC4 PASS (unresolved decisions empty)
  - AC5 PASS (APPROVE-ready)
  - AC6 PASS (this report)
Risks: [R-A-01..R-A-07; Failure 1 sharpened; peer misuse before live scale]
Remaining gaps: [verifier suite; Critic verdict; Wave 05 peer deep-dive]
Critic recommendation: APPROVE-ready
Stop conditions: none — inside MVP; not BLOCKED
```
