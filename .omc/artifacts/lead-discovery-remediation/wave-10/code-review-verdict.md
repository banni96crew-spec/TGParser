# Wave 10 — Code review verdict

- **Captured_at:** 2026-07-27T18:46:27+03:00
- **Reviewer:** SOLE Wave 10 agent (code-review + security + verification)
- **HEAD:** `552eb53adb53ba8569318c096949e22cc127f16d`
- **Verdict:** **REVISE**

## Scope reviewed

Remediation product surface from waves 00–09 evidence + current worktree (collector gateway, discovery/scoring/UI/runtime, Wave 09 harness, PRD counts). No commit/push/merge performed.

## Blocking findings (must revise before APPROVE)

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| CR-1 | Blocker | Global `ruff check src tests` fails (3 issues) | `ruff-out.txt` exit 1 — B009×2, F841×1 in integration tests |
| CR-2 | Blocker | Full `pytest tests -q` does not collect | `pytest-out.txt` exit 2 — `ModuleNotFoundError: No module named 'tests'` from `test_wave09_capacity_recovery.py` importing `tests.harness` while `pyproject.toml` `pythonpath = ["src"]` only |
| CR-3 | Blocker | Wave 09A load command fails on fresh re-run | `wave09a-load-out.txt` exit 2 — capacity/recovery harness not re-verifiable under default pytest |
| CR-4 | Blocker | Quality suite fails | `quality-suite-out.txt` — `validators.test.mjs` hardcodes requirements/AT count **221**, live `validate-prd` reports **254** |

## Non-blocking / notes

| ID | Note |
|---|---|
| CR-N1 | `validate-prd.py` itself is green: 254 req / 254 AT / 67 decisions (parity OK at PRD layer). |
| CR-N2 | Wave 00–09 executor artifacts claim per-wave PASS; Wave 10 does **not** re-certify those focused suites as current global green. |
| CR-N3 | Historical `wave-09/pytest-out.txt` (2 passed) is **stale relative to this collector** — not copied as PASS. |
| CR-N4 | Merge-readiness `--deep` human quiz **NOT_RUN** (requires owner; skill is interactive). |
| CR-N5 | Product architecture spot-check: Telethon stays behind gateway; CSRF on dashboard POSTs; loopback bind asserted — no APPROVE without green global gates. |

## Callers / error paths / performance (spot)

- **Confirmed:** FloodWait → `retry_wait` until exact `until` (Wave 05/09 evidence); active ruleset pin cache added for burst path (Wave 09).
- **Confirmed broken now:** Wave 09 harness package import path under default pytest config.
- **Inference:** Fix is tooling/test packaging (`pythonpath` include repo root / relative imports / `tests/__init__.py` + package layout) plus ruff cleanups and validators fixture sync — **not** performed in Wave 10 (write-only evidence wave).

## Verdict rationale

Release gate requires `code-reviewer = APPROVE` and verifier PASS. Fresh global suites are red. **REVISE** — do not APPROVE, do not weaken tests, do not claim READY.

**Commit/push/merge: NOT PERFORMED**
