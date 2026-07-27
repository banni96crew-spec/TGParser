# Wave 00 — codebase-explorer inventory

- **Agent:** codebase-explorer (read-only; evidence write only)
- **Captured_at:** 2026-07-27 (session Wave 00)
- **Plan audited:** `~/.cursor/plans/telegram-lead-discovery-remediation_7067172d.plan.md` §3
- **Repo HEAD:** `f1b9445` (`коммит перед правками`) on `main`
- **Status:** PASS (inventory complete; no BLOCKED stop condition)

---

## 1. Dirty worktree summary (preserve names)

### Fresh `git status --short` (2026-07-27, this session)

```
 M .omc/plans/telegram-lead-discovery-remediation.md
?? .omc/artifacts/
```

Expanded untracked under artifacts (baseline already captured):

- `.omc/artifacts/lead-discovery-remediation/baseline/capture-meta.txt`
- `.omc/artifacts/lead-discovery-remediation/baseline/git-diff-name-only.txt`
- `.omc/artifacts/lead-discovery-remediation/baseline/git-diff-stat.txt`
- `.omc/artifacts/lead-discovery-remediation/baseline/git-status-short.txt`
- `.omc/artifacts/lead-discovery-remediation/baseline/git-status-untracked-all.txt`
- `.omc/artifacts/lead-discovery-remediation/wave-00/` (this report)

### Product / PRD / tests tree

- **No dirty `src/`, `tests/`, or `docs/` files** relative to HEAD.
- Diff name-only: only `.omc/plans/telegram-lead-discovery-remediation.md`.

### Origin clarity (HC-5)

| Path | Origin | Action |
|---|---|---|
| `.omc/plans/telegram-lead-discovery-remediation.md` | tracked plan copy under `.omc`; modified vs HEAD | preserve |
| `.omc/artifacts/lead-discovery-remediation/**` | Wave 00 baseline/evidence capture | preserve |

**Stop condition:** not triggered — dirty file origins are clear (orchestration artifacts only).  
**Plan HC-5 claim** that unfinished D-059/D-060 product diffs + untracked `003_*.py` remain in worktree is **UPDATED/INVALID for current tree**: migration `003` is **tracked and committed** in `f1b9445`; product tree is clean.

---

## 2. Plan §3 findings — CONFIRMED / UPDATED / INVALID

| # | Finding (plan §3) | Verdict | Fresh evidence | Short proof |
|---|---|---|---|---|
| F1 | Collector does not start | **CONFIRMED** | `src/telegram_lead_discovery/infrastructure/runtime.py:232` | On successful security preflight, `registry.set_component("collector", HealthState.STOPPED, reason_code="deferred")`. `RuntimeCoordinator.start` (`runtime.py:66-138`) starts only `KeywordDiscoveryClaimLoop`; docstring at `:51` says collector worker is “(later)”. No runtime caller of `handle_backfill_job` outside tests. |
| F2 | Live updates absent | **CONFIRMED** | `collector/adapter/telethon_gateway.py:140-148` | `iter_updates()` is an empty stub (`if False: yield …; return`). |
| F3 | Graph discovery stub | **CONFIRMED** | `telethon_gateway.py:109-112` | `get_recommendations(...)` returns `[]`. |
| F4 | Backfill limited incorrectly | **CONFIRMED** | `collector/service.py:198-204` (+ `109-128`) | `enqueue_initial_backfill` payload hard-codes `"limit": 100`; `handle_backfill_job` uses `payload.get("limit", 100)` with single `iter_history` pass (no continuation pagination). |
| F5 | Detection not version-pinned | **CONFIRMED** | `detection/engine.py:98-100` (+ `processing/pipeline.py:230`) | `detect(... rules=None)` falls back to `SEED_RULES`; `process_envelope` calls `detect(norms.analysis_text)` with no rules/version argument. |
| F6 | Deep verification selected separately from service profile | **CONFIRMED** | `source_discovery/worker.py:873-910` (+ `keyword_search.py:606-612`) | Phase G builds candidates then `select_sources_for_deep_verification`; `deep_queries = list(ctx.post_queries[:DEEP_QUERIES_PER_SOURCE])` — first five global post queries, not profile-service-specific selection. |
| F7 | Profile fields only stored | **CONFIRMED** | storage/UI/profile paths vs qualification | `required_service_profiles` / `additional_exclusions` appear in `keyword_profiles.py`, `profile_service.py`, models, dashboard forms — **zero matches** in `opportunity_score.py` or `keyword_search.py`. Not applied in qualification. |
| F8 | Incomplete schema change (003 untracked; live on 002) | **UPDATED** | versions + live DB | **Code:** `003_dismissed_keyword_suppress.py` is tracked (`git ls-files`), revision chain `001→002→003`, Alembic head = `003_dismissed_keyword_suppress`. **Live DB:** still `alembic_version = 002_keyword_source_discovery`; table `dismissed_keyword_sources` **absent**. Suppress cannot be considered complete on live data. |
| F9 | Test baseline not green (158/1; stale head 002; Ruff unused) | **UPDATED (partial)** | `tests/integration/test_storage_settings.py:51-53` | Stale assert `assert rev == "002_keyword_source_discovery"` remains while head is `003` → expected failure mode **CONFIRMED**. Full suite counts (158/1) and Ruff unused-variable claim were **not re-executed** by this explorer (Wave 00 verifier owns fresh suite). |
| F10 | Live data does not pass pipeline | **CONFIRMED (numbers UPDATED)** | sanitized aggregates below | envelopes/messages/leads/outbox = **0**; `initial_backfill` job **queued=1**; opportunities all **band=weak, score=0** (36); recent runs ≈5–6 unique sources/run (not always exactly 6). |

---

## 3. Call-graph map (entry points)

Flow: **discovery → promotion → lifecycle → jobs → collector → processing → detection/scoring → outbox**

```text
UI discovery start
  dashboard/discovery_routes.py:547 discovery_run_start
    → source_discovery/keyword_run.py:141 start_keyword_discovery_run
      → storage/jobs.py:71 enqueue_job (keyword_discovery)

Runtime discovery worker (ONLY production claim loop)
  infrastructure/runtime.py:211 command=="start"
    → :282 RuntimeCoordinator.start
      → :130-131 KeywordDiscoveryClaimLoop.start
        → source_discovery/worker.py:277 claim_and_process_keyword_job
          → :197 process_keyword_discovery_job
            → phases incl. :873 _phase_deep_verification
            → gateway.search / directory / linked discussion
            → opportunity upserts

UI promote
  discovery_routes.py:849 discovery_result_promote
    → source_discovery/promotion.py:167 promote_opportunity_to_candidate
      → TelegramSource lifecycle_state="candidate"

UI approve → monitoring + backfill enqueue
  dashboard/app.py:319 sources_approve
    → source_discovery/service.py:196 approve_source
      → gateway.validate_source
      → lifecycle_state="monitoring" (:235)
      → collector/service.py:198 enqueue_initial_backfill  (limit 100)
      → jobs row job_type=initial_backfill

Collector execute (GAP — no runtime loop)
  collector/service.py:109 handle_backfill_job
    → gateway.iter_history → commit_checkpoint_with_envelope (:76)
  telethon_gateway.py:140 iter_updates  [STUB — never feeds live]
  Callers of handle_backfill_job: tests only
    (e.g. tests/integration/test_source_approve_backfill.py, test_keyword_discovery_e2e.py)

Processing (GAP — no runtime loop)
  processing/pipeline.py:464 process_next_envelope
    → :93 process_envelope
      → detect() detection/engine.py:98
      → score_detection() scoring/engine
      → Lead + LeadScore persist
      → storage/outbox.py:96 enqueue_hot_lead (hot band)
  Callers: tests only (test_pipeline_lead.py, test_shadow_e2e.py, …)

Notifications (GAP — no runtime loop)
  notifications/worker.py:284 process_one / :301 deliver_one
    → claim_outbox → deliver_outbox_item
  Callers: tests only
```

### Runtime startup verdict (AC5)

| Component | Startup behavior | Evidence |
|---|---|---|
| Web (uvicorn) | starts | `runtime.py:278-305` |
| Migrations + job recover | runs | `runtime.py:235-267` |
| Discovery claim loop | starts if Telegram credentials present | `RuntimeCoordinator.start` `:130-131` |
| Collector health | **STOPPED / `deferred`** (or BLOCKED if security) | `runtime.py:227-232` |
| Collector backfill worker | **not started** | no claim loop for `initial_backfill` |
| Live updates consumer | **not started** + gateway stub | `iter_updates` empty |
| Processing / outbox workers | **not started** | no coordinator wiring |

---

## 4. Alembic heads vs version files

| Item | Value |
|---|---|
| Files in `storage/alembic/versions/` | `001_initial.py`, `002_keyword_source_discovery.py`, `003_dismissed_keyword_suppress.py` |
| Chain | `001_initial` → `002_keyword_source_discovery` → `003_dismissed_keyword_suppress` |
| ScriptDirectory heads | **`003_dismissed_keyword_suppress`** (single head) |
| Live DB `alembic_version` | **`002_keyword_source_discovery`** (behind head) |
| Live `dismissed_keyword_sources` | **missing** |

**Do not migrate live DB in Wave 00** (HC-6 / plan gate).

---

## 5. Sanitized live DB aggregates (AC6)

- **Path resolved:** `%LOCALAPPDATA%\TelegramLeadDiscovery\data\app.sqlite3` (exists; size ~708608 bytes)
- **Access:** SQLite read-only URI; **counts only** — no message text, usernames, phones, secrets, session payloads.

### Row counts (selected)

| Table | Count |
|---|---:|
| telegram_event_envelopes | 0 |
| telegram_messages | 0 |
| telegram_message_revisions | 0 |
| leads | 0 |
| lead_scores | 0 |
| notification_outbox | 0 |
| notification_deliveries | 0 |
| telegram_sources | 2 |
| collector_checkpoints | 1 |
| discovery_runs | 10 |
| discovery_run_queries | 1586 |
| source_opportunity_snapshots | 36 |
| source_discovery_evidence | 16 |
| jobs | 10 |
| rule_set_versions | 1 |
| monitoring_rules | 43 |

### Distributions

| Metric | Values |
|---|---|
| source lifecycle | candidate=1, monitoring=1 |
| jobs | initial_backfill/queued=1; keyword_discovery succeeded=7, failed=1, cancelled=1 |
| discovery_runs | succeeded=1, partial=7, failed=1, cancelled=1 |
| opportunity review | unreviewed=25, dismissed=10, promoted=1 |
| opportunity band/score | band=weak×36; score=0×36 |
| distinct opportunity `source_telegram_id` | 11 |
| recent runs unique sources/opps | run10: 5/5; run8: 5/5; run7: 6/6; run6: 5/5; run5: 5/5 (all weak/0) |

---

## 6. ADR-PLAN-001..006 — code alignment snapshot (facts only)

| ADR | Current code fact |
|---|---|
| 001 canonical peer identity | Provisional/dismiss helpers exist in discovery; live suppress table absent; migration 003 not applied live |
| 002 append-only suppress ledger | Migration file present (`003`); not applied to live DB |
| 003 acquisition vs qualification | Worker still uses fixed deep-query slice; no replacement-after-suppress cursor evidenced in §3 scope |
| 004 one runtime coordinator | Coordinator exists but only discovery loop; collector/processing/outbox deferred |
| 005 network I/O outside long TX | Approve path commits before Telethon (`service.py:218-221`); backfill still iterates history inside job session |
| 006 version-pinned rules | Seed fallback still used at detect call site |

---

## 7. Tests / configuration notes (explorer scope)

- Stale migration-head acceptance test: `tests/integration/test_storage_settings.py:51-53`.
- Unit reference to revision 002 module: `tests/unit/test_keyword_opportunity_score.py:137-139` (imports 002 module; does not assert head alone).
- Pipeline/collector/notification behaviors are covered in **integration tests** that call services directly — not via `RuntimeCoordinator` production loops.
- Full `pytest` / `ruff` / `validate-prd` fresh exit codes: **not_run by codebase-explorer** (assigned to Wave 00 verifier).

---

## 8. Risks

1. Live DB remains on revision 002 while code head is 003 — any Wave 02 live migrate without backup/dry-run risks operator data (HC-6).
2. One monitoring source + queued `initial_backfill` will never drain until a collector claim loop exists (Wave 06) and gateway peer/history is correct (Wave 05).
3. Discovery can run and produce only weak/0 opportunities — UI looks “alive” while monitoring pipeline is idle.
4. Plan text still describes untracked 003 / dirty product tree; coordinators must use **this** inventory, not stale HC-5 prose.
5. Test suite expected red until head assertion updated — do not treat green self-report as gate.

---

## 9. Remaining gaps

- Fresh full pytest/ruff/PRD-validator command results (verifier).
- Exact Jaccard / pairwise novelty across last 5 runs (not computed; only unique counts per run).
- Whether Telethon `iter_history` peer uses DB `source_id` incorrectly beyond limit-100 (noted for Wave 05; `HistoryRequest.source_id` passes through gateway `:121-125`).
- Content of modified `.omc/plans/telegram-lead-discovery-remediation.md` vs Cursor plan file (not fully diffed; preserve both).

---

## 10. AC mapping

| AC | Result |
|---|---|
| AC1 §3 findings CONFIRMED/UPDATED/INVALID | **PASS** — table in §2 |
| AC2 call-graph map with file:line | **PASS** — §3 |
| AC3 Alembic heads vs files | **PASS** — §4; head=`003`; live=`002` |
| AC4 dirty worktree summary | **PASS** — §1; origins clear |
| AC5 runtime collector start vs STOPPED | **PASS** — STOPPED/`deferred`; only discovery loop starts |
| AC6 sanitized DB aggregates | **PASS** — §5; secrets skipped |
| AC7 write report to wave-00 path | **PASS** — this file |

---

## Return schema (for coordinator)

```text
Status: PASS
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-00/codebase-explorer-report.md]
Commands:
  - git status --short  → exit 0
  - git ls-files alembic/versions  → exit 0
  - git rev-parse / git log -3  → exit 0
  - uv run python (alembic ScriptDirectory heads) → exit 0
  - python sqlite3 RO aggregates on live app.sqlite3 → exit 0
AC mapping: AC1 PASS, AC2 PASS, AC3 PASS, AC4 PASS, AC5 PASS, AC6 PASS, AC7 PASS
Risks: [live DB behind head; collector deferred; discovery-only weak results; plan HC-5 stale]
Remaining gaps: [full pytest/ruff by verifier; peer-id misuse deep dive; plan-file drift]
Stop conditions: none — dirty origins clear; DB read was aggregate-only
```
