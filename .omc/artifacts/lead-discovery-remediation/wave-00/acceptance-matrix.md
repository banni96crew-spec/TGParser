# Wave 00 — acceptance / gate matrix

- **Agent:** verifier (read-only product; evidence write only)
- **Captured_at:** 2026-07-27T12:20:30Z (approx; see commands.json for per-command timestamps)
- **HEAD:** `f1b9445`
- **Claim type:** baseline captured — **not** product-green

## Wave 00 Gate rows (plan § Wave 00 / Gate)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| G1 | No existing user product diff lost | **PASS** | Fresh `git status --short` / `git diff --name-only`: only `.omc/plans/...` + `?? .omc/artifacts/`. `git status --short -- src/ tests/ docs/` empty. Matches `baseline/git-status-short.txt` and `baseline/git-diff-name-only.txt` (product-risk set unchanged). Critic binding note HC-5 UPDATED: dirty origins are `.omc` only. |
| G2 | All §3 findings CONFIRMED or UPDATED | **PASS** | Explorer §2: F1–F7/F10 **CONFIRMED**; F8/F9 **UPDATED** (F9 suite counts deferred → this verifier). Fresh suite confirms F9: pytest `158 passed / 1 failed` + ruff F841. Critic spot-checks aligned. |
| G3 | No unresolved product decision | **PASS** | Architect §4 empty; ADRs HOLD / HOLD-WITH-NOTES (document in Wave 01, not reopen). Critic: no blocking findings; stop conditions not triggered. |
| G4 | Critic verdict = APPROVE | **PASS** | `wave-00/critic-report.md` Verdict **APPROVE**; Status PASS. |

## Verifier acceptance criteria (dispatch)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| AC1 | All required commands executed; exit codes recorded | **PASS** | `commands.json` — 6 entries with exit codes |
| AC2 | commands.json complete | **PASS** | Fields: command, cwd, started_at, finished_at, exit_code, brief_result; no secrets |
| AC3 | Gate matrix filled PASS/FAIL per row | **PASS** | This file G1–G4 |
| AC4 | Overall Wave 00 verification PASS\|FAIL\|INCOMPLETE | **PASS** | See verification-report.md — Wave00_gate **PASS**; product suites non-green recorded as baseline |
| AC5 | Do not claim product green if tests fail | **PASS** | Explicit claim: **baseline captured**; pytest/ruff/quality-suite non-zero exits preserved |

## Suite baseline snapshot (not a green gate)

| Check | Exit | Counts / note |
|---|---|---|
| validate-prd | 0 | pass; req/AT=223 |
| ruff check src tests | 1 | 1× F841 |
| pytest tests -q | 1 | 158 passed, 1 failed |
| run-quality-suite | 1 | node-tests fail (29 pass / 1 fail: expected req count 221≠223) |
