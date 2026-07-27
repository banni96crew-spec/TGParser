# Wave 01 — acceptance / gate matrix

- **Agent:** verifier (read-only product; evidence write only)
- **Captured_at:** 2026-07-27T12:53:48Z
- **HEAD:** `f1b9445`
- **Claim type:** docs/PRD contract freeze — **not** product-code green

## Wave 01 Gate rows (plan § Wave 01 / Gate)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| G1 | `uv run python tools/quality/validate-prd.py` exits 0 | **PASS** | Fresh run: status=pass; requirements=254; acceptance_tests=254; decisions=67; errors=[] (`commands.json`) |
| G2 | No requirements without acceptance criterion | **PASS** | Validator equal counts 254↔254; TRACEABILITY §8 lists 1:1 REQ ↔ AT ranges for remediation IDs |
| G3 | No two owners of one entity | **PASS** | DOMAIN_MODEL: SRC owns logical identity/suppress; STO owns physical suppress table (STO-017). Critic rereview: no new dual-ownership. Alias DismissedSource/DismissedKeywordSource same owner SRC (non-blocking) |
| G4 | Migration/backfill/rollback defined (suppress/identity) | **PASS** | STO-017 + AT-STO-017 historical backfill; D-062; TRACEABILITY §8 Wave 02 mandate; STO §12 pre-migration backup restore |
| G5 | Thresholds concrete | **PASS** | NFR-QLT-006: hot≥0.80, hot+warm≥0.70, recall≥0.75, novelty≥0.80, Jaccard≤0.60; AT-OBS-016 aligned; graph depth=2 |
| G6 | TRACEABILITY references all new IDs | **PASS** | TRACEABILITY §8: D-061..067; SRC-033..045; COL-023..026; PROC-019; DET-016; STO-017..018; UI-019..024; OBS-019..021; INF-022; NFR-PERF-006..008; NFR-REL-008; NFR-QLT-006 |
| G7 | Product runtime still excludes AI / outreach / private auto-join | **PASS** | SRC: auto-join + AI/LLM out-of-scope; COL excludes automatic join; DET/UI/NOT exclude AI / outreach |
| G8 | Critic rereview = APPROVE | **PASS** | `critic-rereview-report.md` Verdict **APPROVE**; mandatory fixes 1–2 CLOSED |
| G9 | No product `src/` source changes in this wave | **PASS** | `git diff` for `src/**/*.py` empty; only `__pycache__` dirty under src |

## Verifier acceptance criteria (dispatch)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| AC1 | Fresh validate-prd + git commands recorded | **PASS** | `commands.json` |
| AC2 | Manual plan Wave 01 checks filled | **PASS** | G2–G8 above |
| AC3 | Overall Wave 01 verification PASS|FAIL|INCOMPLETE | **PASS** | `verification-report.md` — Wave01_gate **PASS** |
| AC4 | Do not claim product code green | **PASS** | Explicit: docs freeze only; product suites / quality-suite not claimed green |

## Out of gate (recorded, not blocking)

| Check | Result | Note |
|---|---|---|
| quality-suite expected-count | **not_run** | Plan notes drift may still fail; Wave 01 primary is validate-prd |
| ruff / pytest product suites | **not_run** | Not Wave 01 gate; do not claim green |
