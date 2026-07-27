# Wave 00 — planner drift-adjusted sequencing / acceptance review

- **Agent:** planner (read-only product/docs; evidence write only)
- **Captured_at:** 2026-07-27 (session Wave 00)
- **Plan audited:** `~/.cursor/plans/telegram-lead-discovery-remediation_7067172d.plan.md`
- **Explorer input:** `.omc/artifacts/lead-discovery-remediation/wave-00/codebase-explorer-report.md` (**PASS**)
- **Repo HEAD:** `f1b9445` on `main`
- **Status:** **PASS** (sequencing ratified with minimal wording patches; no MVP scope break; Wave 01 not blocked)

---

## 1. Goal and method

Produce a drift-adjusted sequencing / acceptance review of the approved remediation plan against **current** codebase facts from the explorer report. This report does **not** rewrite product decisions; it states what must stay, what is stale, and whether Wave 00→10 dependency order remains valid.

### Inputs used

| Input | Role |
|---|---|
| Cursor plan (full) | Orchestration contract, ADRs, waves, §10 matrix |
| Explorer report PASS | Fresh CONFIRMED/UPDATED findings F1–F10 |
| `git status --short` (this session) | Confirm dirty tree = `.omc` only |
| Spot checks | `003` migration body; `DECISION_LOG` D-059/D-060; stale head assert; SRC-032 presence |

---

## 2. Verdict summary

| Question | Answer |
|---|---|
| Wave 00→10 dependency graph still valid? | **YES** — keep order; apply **minimal wording / ownership patches** below (report-only; do not rewrite plan file in Wave 00) |
| Unresolved product decision blocking Wave 01? | **NONE** — ADRs 001–006 + existing D-059/D-060/SRC-032 are sufficient to start PRD/contract freeze |
| Scope outside MVP? | **NO** — stop condition not triggered; not **BLOCKED** |
| Rewrite whole plan? | **NO** — Architect/Critic treat listed claims as **UPDATED** |

---

## 3. What must stay (do not reopen)

These remain binding for Architect/Critic/executor waves:

1. **HC-0..HC-4, HC-6..HC-8** — coordinator-only writes, preflight, skills inventory, author≠verifier, live fail-closed, PRD-first, atomic wave gates.
2. **ADR-PLAN-001..006** — canonical peer identity, append-only suppress ledger, acquisition≠qualification, runtime loops, network I/O outside long TX, version-pinned rules. Explorer §6 shows code still misaligned; ADRs remain the design targets.
3. **Product success gates** (plan §2) — permanent suppress=0 recurrence, replacement/`pool_exhausted`, novelty, weak hidden by default, 100/1000 capacity, burst, calibration thresholds, loopback security.
4. **Out of scope** — AI/LLM runtime, private auto-join, Stars/paid search, auto-outreach, multi-user/RBAC.
5. **Dependency edges** (plan §8):
   - `W00 → W01 → W02`
   - `W02 → W03` and `W02 → W04` (parallel only under ownership split)
   - `W03+W04 → W05 → W06`
   - `W01 → W07` (rules can proceed after contracts; still joins UI at W08)
   - `W06+W07 → W08 → W09 → W10`
6. **§10 root-cause → wave ownership** — still the correct fix ownership map (see §6 of this report).
7. **Live DB migrate / Telegram live smoke** — remain **Wave 09 only** after backup/approval (HC-6). Wave 00–08 use temp DB.

---

## 4. Stale plan claims (Architect/Critic MUST treat as UPDATED)

| Plan locus | Stale claim | Current fact (explorer + this session) | How to treat |
|---|---|---|---|
| **HC-5** | Unfinished D-059/D-060 product diffs + **untracked** `003_*.py` in worktree | Product/`src`/`tests`/`docs` **clean** at HEAD `f1b9445`. Dirty: `M .omc/plans/...`, `?? .omc/artifacts/`. `003` is **tracked** (`git ls-files`). D-059/D-060 already in `DECISION_LOG.md`. | **UPDATED:** HC-5 now means preserve **`.omc` orchestration artifacts**; do not assume unfinished product diffs. Baseline still required before any write wave. |
| **§3 F8 / Wave 02 todo** | “Незавершённая schema change”; “untracked 003”; Wave 02 “завершить … миграцию 003” as if file missing | File present; Alembic head = `003_dismissed_keyword_suppress`; **live DB still `002`**; table `dismissed_keyword_sources` **absent** on live. | **UPDATED:** Wave 02 owns **semantics completion + temp migrate/tests**, not “add untracked file”. Live apply remains Wave 09. |
| **§3 F8 implication** | Suppress incomplete because migration missing from repo | Suppress incomplete because (a) live not migrated, (b) `003.upgrade()` creates **empty** table and **returns without historical dismiss backfill** (`003_dismissed_keyword_suppress.py:61-65`) | **UPDATED gap:** Wave 02 must add/prove **idempotent historical backfill** (plan Failure 1 still live). |
| **§3 F9** | “158 passed, 1 failed; Ruff: 1 unused variable” as current truth | Stale head assert **CONFIRMED** (`tests/integration/test_storage_settings.py:51-53` expects `002_…`). Full suite/Ruff **not_run** by explorer (verifier owns). | **UPDATED (partial):** treat head-assert as known red; do **not** cite 158/1 or Ruff until Wave 00 verifier fresh commands. |
| **§3 F10 numbers** | “exactly 6 unique sources” | Recent runs ≈5–6 unique; envelopes/messages/leads=0; all opportunities weak/0; `initial_backfill` queued=1 | **UPDATED numbers**; symptom **CONFIRMED**. |
| **Wave 02 todo one-liner** | Implies migration 003 is unfinished product artifact | Migration revision exists in tree; product work remaining is identity/suppress behavior, backfill, tests, reconsider path per ADRs | Soften todo language in coordinator notes; **do not skip Wave 02**. |

### Confirmed unchanged (stay as §3 evidence)

| # | Finding | Wave owner |
|---|---|---|
| F1 | Collector `STOPPED`/`deferred`; no production backfill claim loop | Wave 06 (+ peer/history correctness Wave 05) |
| F2 | `iter_updates()` empty stub | Wave 05 |
| F3 | `get_recommendations()` returns `[]` | Wave 04 |
| F4 | Backfill hard-coded limit 100; no continuation | Wave 05 |
| F5 | `detect()` → `SEED_RULES` fallback; no version pin at call site | Wave 07 |
| F6 | Deep verification uses first five global post queries | Wave 03 |
| F7 | `required_service_profiles` / `additional_exclusions` stored, not applied in qualification | Wave 03 |
| F10 | Live pipeline idle (0 envelopes/leads); discovery weak-only | Waves 05–08 (root), Wave 09 proof |

---

## 5. Sequencing: stay vs minimal patches

### 5.1 Graph validity

```text
W00 → W01 → W02 → W03 ─┐
                 └→ W04 ─┴→ W05 → W06 ─┐
           W01 ──────────────→ W07 ──┴→ W08 → W09 → W10
```

**Confirmed valid** against current code:

- Contracts/PRD freeze (**W01**) still required before enlarging product behavior beyond committed D-059/D-060 (novelty/replacement, graph budgets, runtime loops, rule pinning, capacity metrics, reconsider/audit details for suppress).
- Durable suppress/identity (**W02**) still required: live lag + empty-table migration without historical backfill + stale head test.
- Keyword quality (**W03**) and graph (**W04**) still depend on suppress/canonical identity to avoid re-polluting pools.
- Gateway/backfill/live (**W05**) before runtime loops (**W06**) — explorer shows approve enqueues backfill but nothing claims it; live stub.
- Detection (**W07**) can proceed after **W01** in parallel with mid-pipeline waves, joining at **W08** — edge `W01→W07` remains correct.
- Capacity/pilot (**W09**) after UI/obs (**W08**) — correct for operator visibility during pilot.
- Independent release (**W10**) last — correct.

### 5.2 Minimal sequencing patches (coordinator notes only; plan file unchanged in Wave 00)

| Patch ID | Change | Why |
|---|---|---|
| **P-SEQ-01** | Treat HC-5 baseline as “preserve `.omc` + any future product dirty”; remove assumption of unfinished D-059/D-060 diffs | Explorer + fresh `git status` |
| **P-SEQ-02** | Wave 02 entry criteria: **head already `003` in repo**; work = complete ledger semantics (historical backfill, alias/provisional merge, reconsider, retention immunity), update head assert, **temp** `002→003` suites | File exists; upgrade incomplete vs ADR-002 / Failure 1 |
| **P-SEQ-03** | Explicitly forbid live `tld migrate` until Wave 09 Part B | Live still on `002`; HC-6 |
| **P-SEQ-04** | Wave 03∥04 ownership split unchanged; if Wave 02 discovers shared model changes needed beyond PRD freeze, serialize 03/04 | Already in plan §8 |
| **P-SEQ-05** | Do **not** collapse Wave 02 into “already done” because suppress helpers exist in `worker.py` | Live table missing; no historical backfill SQL; ADR-001 merge/reconsider not proven complete |

**No wave reorder. No wave merge. No new wave.**

### 5.3 Wave 01 blockers

| Candidate blocker | Blocking Wave 01? | Notes |
|---|---|---|
| Live DB on 002 | **No** | Ops/Wave 09; Wave 01 is docs-only |
| Migration 003 incomplete backfill | **No** | Product code Wave 02 after PRD defines backfill invariants |
| D-059/D-060 already decided | **No** — enables Wave 01 | Writer extends TRACEABILITY/contracts for remaining ADR gaps; does not reopen D-059/D-060 without Critic |
| ADR-PLAN-001..006 not yet fully mirrored as new MUST/AT beyond SRC-032 | **No** — this **is** Wave 01 work | Not a missing decision; missing **documentation freeze** |
| Open product fork (AI ranking, private join, etc.) | **No** | Explicitly rejected in plan §4 |

**Wave 01 may start after Wave 00 Critic APPROVE + verifier baseline.**

---

## 6. Explorer findings → wave ownership (§10 reuse)

| Explorer / §3 | Plan §10 root cause | Owning wave(s) | Evidence note |
|---|---|---|---|
| F8 UPDATED + empty 003 + live 002 | Dismiss not durable across runs / historical migration | **02** (+ live apply **09**) | Backfill missing in `003.upgrade` |
| F9 partial (head assert 002) | (schema test hygiene; called out in Wave 02 impl) | **02** | `test_storage_settings.py:51-53` |
| Identity/alias gaps (ADR-001 snapshot) | Username/ID/alias duplicates | **02** | Explorer §6 ADR-001 |
| Replacement after suppress / novelty | After suppress no replacement; same directory tops | **03** / **03+04** | F6/F7 related acquisition |
| F7 profile fields unused | Profile exclusions/services not applied | **03** | Confirmed |
| Weak-only opportunities + UI | Low-quality directory-only; UI hides reasons | **03** + **08** | F10 bands |
| F3 graph stub | Graph discovery stub | **04** | Confirmed |
| F2 live stub | Telethon live updates stub | **05** | Confirmed |
| F4 limit 100 / no pagination | Backfill limit/peer/TX | **05** | Confirmed; peer deep-dive still gap |
| F1 collector deferred; no claim loops | Workers don’t start; pipeline only in tests | **06** | Confirmed |
| F5 SEED_RULES fallback | Rules always from Python seed | **07** | Confirmed |
| Calibration absent | No calibration | **07** | Still required |
| F10 idle monitoring / weak UI | UI + runtime + capacity proof | **08** then **09** | Confirmed |
| Stale release confidence | Old evidence | **10** | Unchanged |

---

## 7. Risk register updates (Wave 00 outputs)

| ID | Risk | Likelihood | Impact | Mitigation / owner | Drift vs plan §11 |
|---|---|---|---|---|---|
| R-00-1 | Coordinators follow stale HC-5 / “untracked 003” and skip Wave 02 or fight non-existent dirty product diffs | Med | High | This report + explorer; Critic must cite UPDATED facts | **New** (plan HC-5 drift) |
| R-00-2 | Live DB remains on 002; premature migrate without backup | Med | Critical | HC-6; Wave 09 Part B only; Wave 02 temp DB only | Aligns Failure 5 |
| R-00-3 | Migration 003 creates empty suppress table → “green migrate” without historical dismiss backfill | High | High | Wave 02 must prove backfill counts; Failure 1 still active | **Sharpened** — confirmed by reading `003` body |
| R-00-4 | Discovery-only runtime looks healthy while monitoring pipeline idle | High | High | Waves 05–06; health must not stay `deferred` forever | Aligns Failure 2 |
| R-00-5 | Novelty without quality (weak→weak) | Med | High | Waves 03/07/08 gates | Aligns Failure 3 |
| R-00-6 | SQLite lock under backfill/burst | Med | High | ADR-005; Waves 05/09 | Aligns Failure 4 |
| R-00-7 | Citing 158/1 or Ruff without fresh verifier run | Med | Med | Wave 00 verifier owns suite | **New** (F9 partial) |
| R-00-8 | Partial suppress code in `worker.py` creates false “Wave 02 done” impression while live table missing | Med | High | Gate on multi-run recurrence + live dry-run counts in Wave 09 | **New** |

---

## 8. Acceptance criteria mapping (this planner deliverable)

| AC | Result | Evidence |
|---|---|---|
| 1. Confirm Wave 00→10 graph OR minimal patches | **PASS** | §5 — graph stays; patches P-SEQ-01..05 wording only |
| 2. List stale claims for Architect/Critic | **PASS** | §4 |
| 3. Wave 01 blockers | **PASS** — none | §5.3 |
| 4. Map findings → waves via §10 | **PASS** | §6 |
| 5. Risk register updates for Wave 00 | **PASS** | §7 |
| 6. Write `planner-report.md` under wave-00/ | **PASS** | this file |

---

## 9. Recommendation for Architect

1. **Steelman ADRs against UPDATED facts**, not against HC-5 prose: product tree clean; `003` committed but **semantically incomplete** (no historical backfill); live DB behind head.
2. Focus design deltas on:
   - **Suppress ledger completeness:** historical backfill algorithm, alias/provisional merge, reconsider, retention immunity, idempotent `002→003` on populated DB.
   - **Runtime topology (ADR-004):** how collector/processing/outbox loops attach without violating single-writer SQLite (ADR-005).
   - **Rule pinning (ADR-006):** remove `SEED_RULES` runtime fallback path safely.
3. Do **not** propose reordering waves; do **not** expand MVP (AI, private join, Stars).
4. Call out that **D-059/D-060/SRC-032 exist** — Wave 01 should **extend** contracts for remaining ADR gaps rather than duplicate dismiss decisions.
5. Hand Critic: sequencing **APPROVE-candidate** pending Architect review; only **REVISE** if Architect finds a hard contract conflict requiring wave split (none found by planner).

---

## 10. Remaining gaps (not planner ownership)

- Fresh `pytest` / `ruff` / `validate-prd` exit codes → **Wave 00 verifier**.
- Exact Jaccard across last 5 discovery runs → optional; not required to ratify sequencing.
- Deep peer-id misuse in `iter_history` beyond limit-100 → **Wave 05** architect/executor.
- Diff content of `.omc/plans/telegram-lead-discovery-remediation.md` vs Cursor plan → preserve both; coordinator may later sync todos only.
- Critic verdict and Architect steelman → **next Wave 00 agents**.

---

## Return schema (for coordinator)

```text
Status: PASS
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-00/planner-report.md]
Commands:
  - git status --short → exit 0 (M .omc/plans/...; ?? .omc/artifacts/)
  - git rev-parse --short HEAD → f1b9445
  - git ls-files .../003_dismissed_keyword_suppress.py → tracked
  - Read/Grep spot-checks: 003 body, DECISION_LOG D-059/D-060, test_storage_settings head assert, SRC-032
AC mapping:
  - AC1 PASS (graph valid; P-SEQ-01..05 patches only)
  - AC2 PASS (stale claims listed)
  - AC3 PASS (no Wave 01 product-decision blockers)
  - AC4 PASS (findings→waves via §10)
  - AC5 PASS (risk register updated)
  - AC6 PASS (this report)
Risks: [R-00-1..R-00-8; Failure 1 sharpened by empty 003 upgrade]
Remaining gaps: [verifier suite; Jaccard; peer deep-dive; Architect/Critic]
Recommendation for Architect: steelman ADRs on UPDATED facts; keep wave order; complete suppress backfill design; do not reopen MVP out-of-scope
Stop conditions: none — plan stays inside MVP; not BLOCKED
```
