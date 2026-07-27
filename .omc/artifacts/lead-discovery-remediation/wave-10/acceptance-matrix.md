# Wave 10 — Acceptance matrix

Captured_at: **2026-07-27T18:46:27+03:00**  
Wave10_gate: **FAIL**  
Commit/push/merge: **NOT PERFORMED**

## Release gate criteria (plan §Wave 10)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | `code-reviewer = APPROVE` | **FAIL** | Verdict **REVISE** — `code-review-verdict.md` |
| 2 | Security overall risk ≤ LOW; no unresolved HIGH/CRITICAL | **PASS** | overall **LOW**; HIGH/CRITICAL **none** — `security-review-verdict.md` |
| 3 | Verifier = PASS, confidence HIGH | **FAIL** | Verifier **FAIL**, confidence HIGH on red suites — `verification-report.md` |
| 4 | 100% MUST requirements have AT | **PASS** (PRD layer) | `validate-prd.py` 254 req / 254 AT, errors=[] |
| 5 | Release evidence matches current diff + fresh commands | **PASS** | `docs/engineering/MVP_RELEASE_EVIDENCE.md` rewritten from this capture only |
| 6 | Merge-readiness deep ≥0.90 + all dimensions | **NOT_RUN** | Skill present; interactive human quiz not executed |
| 7 | Human owner decides commit/push/merge | **STOP** | **NOT PERFORMED** |

## Required fresh commands

| Command | Exit | Matrix |
|---|---:|---|
| `uv run python tools/quality/validate-prd.py` | 0 | **PASS** |
| `uv run ruff check src tests` | 1 | **FAIL** |
| `uv run pytest tests -q` | 2 | **FAIL** |
| `node tools/quality/run-quality-suite.mjs` | 1 | **FAIL** |
| `node tools/quality/ci-recompute.mjs` | 0 | **PASS** (observe_only; authoritative CI blocked) |
| Wave 09A load pytest | 2 | **FAIL** |

## Wave 09 Part B

| Item | Status |
|---|---|
| Live Windows pilot | **NOT_RUN** |
| Operator approval | **BLOCKED** |
| Claim “Windows pilot complete” | **FORBIDDEN / not claimed** |

## Root-cause AC (plan §10) — Wave 10 stance

Wave 10 does **not** re-certify waves 02–09 focused AC as global green. Fresh global gates are red; prior wave PASS claims remain historical artifacts only.

| Root cause theme | Owning wave | Wave 10 status |
|---|---|---|
| Dismiss / identity / suppress | 02 | Historical PASS artifact; not re-proven globally |
| Replacement / novelty / eligibility | 03 | Historical |
| Graph public-only | 04 | Historical + security spot PASS |
| Collector live/backfill | 05 | Historical + security spot PASS |
| Runtime workers / pipeline | 06 | Historical |
| Rules / calibration | 07 | Historical |
| UI / observability | 08 | Historical |
| 100/1000 capacity + recovery | 09A | Historical PASS; **fresh re-run FAIL** |
| Live pilot | 09B | **NOT_RUN** |
| Stale release evidence | 10 | **Addressed** by rewriting evidence to fail honestly |

## Overall

| Field | Value |
|---|---|
| Wave10_gate | **FAIL** |
| READY next wave | **no** — STOP for owner |
| Invented PASS | **none** |
