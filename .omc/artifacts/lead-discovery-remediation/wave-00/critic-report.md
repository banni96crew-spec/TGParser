# Wave 00 — critic fail-closed plan ratification

- **Agent:** critic (read-only product/docs/plan; evidence write only)
- **Captured_at:** 2026-07-27 (session Wave 00)
- **Plan audited:** `~/.cursor/plans/telegram-lead-discovery-remediation_7067172d.plan.md`
- **Inputs:** codebase-explorer-report.md (**PASS**), planner-report.md (**PASS**), architect-report.md (**PASS**)
- **Repo HEAD:** `f1b9445` on `main`
- **Status:** **PASS** (ratification complete)

---

## Verdict

**APPROVE**

Wave 00 evidence chain (explorer → planner → architect) independently re-checks as consistent with the current worktree and code. Product tree is clean (dirty origins are `.omc` orchestration only — no user product diff at risk). Plan §3 findings F1–F7/F10 are CONFIRMED; F8 and F9 are explicitly UPDATED with fresh evidence (F9 suite totals deferred to Wave 00 verifier). ADR-PLAN-001..006 HOLD / HOLD-WITH-NOTES with no ADR redesign and no open product fork. Dependency graph W00→W10 remains valid; Wave 02 stays mandatory (committed `003` is semantically incomplete). MVP out-of-scope is intact. Execution may proceed to Wave 00 verifier baseline, then Wave 01 under the binding notes below.

---

## Plan Review

### Gate criteria (Wave 00)

| Criterion | Result | Evidence |
|---|---|---|
| No existing user product diff lost; dirty origins clear | **PASS** | Fresh `git status --short`: `M .omc/plans/...`, `?? .omc/artifacts/`; `src/`/`tests/`/`docs/` clean; baseline `git-status-short.txt` matches; explorer §1 |
| All §3 findings CONFIRMED or UPDATED with fresh evidence | **PASS** | Explorer §2 table; critic spot-checks below |
| No unresolved product decision | **PASS** | Architect §4 empty; planner §5.3; ADR HOLD/HOLD-WITH-NOTES = document in Wave 01, not reopen |
| Plan executable inside MVP | **PASS** | No AI/private-join/Stars/outreach expansion; stop condition not triggered |

### Blocking findings

**None.**

### Binding notes (mandatory for coordinator; do **not** reopen ADRs)

These are operational/wording constraints that make APPROVE safe. Treating them as optional is a gate failure for later waves.

1. **HC-5 STALE → UPDATED (P-SEQ-01):** Do **not** assume unfinished D-059/D-060 product diffs or untracked `003_*.py`. Current dirty set is `.omc` only; `003` is tracked at HEAD `f1b9445`. Preserve `.omc` artifacts/plans; capture baseline before any write wave.
2. **§3 F8 UPDATED (P-SEQ-02/05):** Wave 02 is **not** “add migration file”. Wave 02 owns suppress/identity **semantics completion**: historical dismiss backfill, alias/provisional merge proofs, reconsider path, retention immunity, fix stale head assert, temp `002→003` suites. **Do not skip Wave 02.**
3. **Live migrate forbidden until Wave 09 Part B (P-SEQ-03 / HC-6):** Live DB remains on `002`; table `dismissed_keyword_sources` absent. Waves 00–08 use temp DB only.
4. **ADR-001 / ADR-002 HOLD-WITH-NOTES for Wave 01 writer:** Freeze provisional identity lifecycle (cannot enter `monitoring`; atomic merge to numeric peer). Interpret “append-only suppress” as: membership permanent until explicit reconsider; rows not deleted by retention/retry; claim fields may upsert; optional audit events may append. Historical backfill invariant is MUST for Wave 02.
5. **F9 suite counts:** Do **not** cite “158 passed / 1 failed” or Ruff unused-variable as current truth until Wave 00 verifier fresh commands. Stale head assert at `tests/integration/test_storage_settings.py:51-53` remains a known red mode.
6. **Capacity / production-ready claims:** Invalid until Wave 09 evidence. Current stubs (collector `deferred`, empty `iter_updates`, no processing/outbox loops) make early PASS claims false.

### Non-blocking improvements

1. When the coordinator next updates plan todo statuses, soft-patch HC-5 / Wave 02 one-liner prose to match UPDATED facts (optional; binding notes already govern execution).
2. Diff `.omc/plans/telegram-lead-discovery-remediation.md` vs Cursor plan file for todo/status drift (preserve both; sync carefully).
3. Optional Jaccard across last 5 discovery runs — not required to leave Wave 00.
4. Wave 05 peer deep-dive (`HistoryRequest.source_id` → Telethon entity) remains a known gap; already owned by Wave 05 — do not expand Wave 00.

### Missing verification or rollback

| Wave 00 required output | Status |
|---|---|
| Dirty-worktree manifest | **Present** — `.omc/artifacts/.../baseline/git-status-*.txt`, `git-diff-*.txt`, explorer §1 |
| File/line current-state map | **Present** — explorer §2–§3 |
| Sanitized live DB aggregates | **Present** — explorer §5 (counts only) |
| Updated risk register | **Present** — planner §7 (R-00-1..8) + architect §7 (R-A-01..07) |
| Critic `APPROVE` | **This report** |
| Test / ruff / PRD-validator baseline | **Explicitly deferred** to Wave 00 `verifier` (HC-4; explorer/planner/architect remaining gaps) |
| Wave kit `verification-report.md` / `commands.json` / `acceptance-matrix.md` / `changed-files.sha256` / `rollback.md` | **Deferred** to Wave 00 verifier (ratification agents produce author reports only) |

**Rollback for Wave 00:** N/A (no product writes). Preserve baseline + wave-00 reports; do not delete `.omc/artifacts`.

---

## HC-0..HC-8 consistency with proposed execution

| HC | Consistent? | Notes |
|---|---|---|
| **HC-0** coordinator-only product writes | **YES** | Wave dispatch lists leaf roles; main agent updates plan status/evidence only |
| **HC-1** preflight + module PRD reads | **YES** | Dispatch requires sequential-thinking + Pre-flight; Wave 01+ read module PRDs |
| **HC-2** repo-local skills only | **YES** | plan/verify/merge-readiness/agent-preflight; no quarantined LeadGenerator skills |
| **HC-3** mandatory dispatch schema | **YES** | Plan §0/§1/§9 encode Role/Wave/Goal/ownership/AC/stop |
| **HC-4** author ≠ verifier | **YES** | Every write wave ends with independent verifier; Wave 00 suite owned by verifier not explorer |
| **HC-5** dirty worktree protect | **YES with UPDATED facts** | Intent preserved; prose stale — binding note #1; baseline captured |
| **HC-6** live/secrets fail-closed | **YES** | No live Telegram/Bot/DB mutate until Wave 09 approval; fake gateway + temp SQLite for tests |
| **HC-7** PRD-first | **YES** | Wave 01 before product code; validate-prd gate |
| **HC-8** atomic wave gates | **YES** | Implementation + verification reports, commands, AC matrix, rollback, sha256 required before next wave |

Multi-agent waves, verifier gates, and live fail-closed are **aligned** with HC-0..HC-8 under UPDATED HC-5.

---

## Independent spot-checks (critic)

| Claim | Critic check | Result |
|---|---|---|
| Dirty = `.omc` only | `git status --short`; empty status for `src/` `tests/` `docs/` | **CONFIRMED** |
| `003` tracked | `git ls-files .../003_dismissed_keyword_suppress.py` | **CONFIRMED** |
| HEAD | `git rev-parse --short HEAD` → `f1b9445` | **CONFIRMED** |
| F1 collector deferred | `runtime.py:232` `STOPPED`/`deferred`; discovery loop `:130` | **CONFIRMED** |
| F2/F3 stubs | `get_recommendations` returns `[]`; `iter_updates` `if False` | **CONFIRMED** |
| F5 SEED_RULES | `detection/engine.py:100` | **CONFIRMED** |
| F8 empty upgrade | `003.upgrade():61-65` create-then-`return` (no historical INSERT) | **CONFIRMED** |
| F9 stale head assert | `test_storage_settings.py:51-53` expects `002_...` | **CONFIRMED** |

Claims **not** re-executed by critic (accepted as deferred/owned elsewhere):

- Full pytest / ruff / validate-prd exit codes → Wave 00 verifier
- Live SQLite aggregate re-query → explorer already sanitized; HC-6 avoids unnecessary live re-open
- Exact Telethon peer/access-hash design → Wave 05

---

## Decision challenge

- **Favored approach:** Keep ADR-PLAN-001..006 and W00→W10 order; complete suppress semantics in Wave 02 despite committed `003`; PRD freeze in Wave 01; live migrate only in Wave 09.
- **Strongest alternative:** Collapse Wave 02 into “migration already landed” and jump to Wave 03 novelty work.
- **Unresolved trade-off:** **Rejected.** Alternative fails Failure 1 (empty table / no historical backfill / live still on `002`) and R-A-01/R-00-3. Architect HOLD-WITH-NOTES on ADR-002 correctly keeps Wave 02 mandatory.

Secondary steelman (ADR-001 provisional key vs `source_telegram_id` NOT NULL): schema representation is Wave 01 contract freeze work from an already-accepted ADR, **not** an open product fork. Escalate to BLOCKED only if Wave 01 writer invents a conflicting identity model — none present now.

---

## Stop conditions

| Stop condition | Triggered? |
|---|---|
| Cannot determine origin of intersecting dirty file | **No** — `.omc` only |
| Live DB cannot be read without sensitive disclosure | **No** — explorer used aggregate-only RO counts |
| Plan requires new scope outside MVP | **No** |

---

## AC mapping (this critic deliverable)

| AC | Result |
|---|---|
| 1. Explicit verdict + one-paragraph rationale at top | **PASS** — APPROVE |
| 2. If REVISE: numbered mandatory changes | **N/A** |
| 3. If REJECT: stop conditions | **N/A** — none triggered |
| 4. HC-0..HC-8 consistency with multi-agent / verifier / live fail-closed | **PASS** — table above; HC-5 UPDATED |
| 5. Wave 00 required outputs present or deferred to verifier | **PASS** — suite baseline deferred; others present |
| 6. Write `critic-report.md` | **PASS** — this file |

---

## Risks carried forward

1. **R-00-1 / R-A-01:** Coordinator follows stale HC-5 / “003 done” → skips Wave 02 — **mitigated by binding notes; still High if ignored**
2. **R-00-3 / Failure 1:** Empty `003.upgrade` → false-green migrate without historical backfill — Wave 02 must prove counts
3. **R-A-03:** Live pilot before peer-id fix — Wave 05 gate before Wave 09 scale-up
4. **R-A-04 / Failure 2:** Healthy discovery masks permanent `collector=deferred` — Wave 06
5. **R-00-7:** Citing 158/1 without verifier — Wave 00 verifier next

---

## Remaining gaps

- Wave 00 verifier: fresh `validate-prd` / `ruff` / `pytest` / quality-suite + evidence kit files
- Coordinator may soft-sync plan HC-5 prose when updating todos (non-blocking)
- Wave 01 must encode ADR-001/002 HOLD-WITH-NOTES as MUST/AT without reopening D-059/D-060

---

## Return schema (for coordinator)

```text
Status: PASS
Verdict: APPROVE
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-00/critic-report.md]
Commands:
  - MCP sequentialthinking (3+ thoughts) → ok
  - Read: plan, explorer, planner, architect, agent-preflight, plan skill (partial)
  - git status --short / -sb / diff --stat / name-only → .omc only
  - git ls-files 003_*.py → tracked; rev-parse → f1b9445
  - git status --short -- src/ tests/ docs/ → empty
  - Read/Grep spot-checks: runtime.py, telethon_gateway.py, engine.py, 003 upgrade, test_storage_settings.py
AC mapping:
  - AC1 PASS (APPROVE + rationale)
  - AC2 N/A
  - AC3 N/A (stops not triggered)
  - AC4 PASS (HC-0..HC-8; HC-5 UPDATED)
  - AC5 PASS (suite deferred to verifier; other outputs present)
  - AC6 PASS (this report)
Risks: [R-00-1 skip Wave 02; Failure 1 empty backfill; peer misuse before live; deferred suite citation]
Remaining gaps: [Wave 00 verifier suite + evidence kit; optional plan HC-5 prose sync]
Stop conditions: none
Next: Wave 00 verifier baseline → on PASS, Wave 01 PRD/contract freeze under binding notes
```
