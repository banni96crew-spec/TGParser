# MVP release evidence bundle

| Field | Value |
|---|---|
| Product | Telegram Lead Discovery |
| Captured_at | 2026-07-27T18:46:27+03:00 (Wave 10 independent gates) |
| HEAD | `552eb53adb53ba8569318c096949e22cc127f16d` |
| Schema / Alembic | Product migrations present through remediation (`003_dismissed_keyword_suppress` in tree); **live DB migrate = NOT_RUN** (Wave 09 Part B blocked) |
| Owner gate | Phase 0 freeze + authorization 2026-07-16 (unchanged authority) |
| Status | **`fail`** — Wave 10 global gates not green |
| Commit/push/merge | **NOT PERFORMED** |
| Wave 09 Part B (live pilot) | **NOT_RUN** |

## Wave 10 fresh mandatory checks

| Check | Result | Exit | Notes |
|---|---|---:|---|
| `uv run python tools/quality/validate-prd.py` | **pass** | 0 | 254 requirements / 254 acceptance tests / 67 decisions; `errors: []` |
| `uv run ruff check src tests` | **fail** | 1 | B009×2 (`test_canonical_identity_suppress.py`); F841 (`test_source_approve_backfill.py:139`) |
| `uv run pytest tests -q` | **fail** | 2 | Collection error: `ModuleNotFoundError: No module named 'tests'` (`test_wave09_capacity_recovery.py` → `tests.harness`) |
| `node tools/quality/run-quality-suite.mjs` | **fail** | 1 | `validators.test.mjs` expects requirements count **221**; live count **254** |
| `node tools/quality/ci-recompute.mjs` | **pass** | 0 | `observe_only`; `authoritative_ci=blocked`; `at_gov_009=local_only`; `at_gov_010=not_run` |
| Wave 09A load (`pytest tests/integration/test_wave09_capacity_recovery.py`) | **fail** | 2 | Same import failure; historical wave-09 “2 passed” **not** copied |

Evidence directory: `.omc/artifacts/lead-discovery-remediation/wave-10/`  
(`commands.json`, `verification-report.md`, `code-review-verdict.md`, `security-review-verdict.md`, `acceptance-matrix.md`, command logs).

## Independent reviews (Wave 10)

| Review | Result |
|---|---|
| Code review | **REVISE** |
| Security overall risk | **LOW** — unresolved HIGH/CRITICAL: **none** |
| Verifier | **FAIL** (confidence HIGH) |
| Merge-readiness deep | **NOT_RUN** (requires human owner quiz) |

## Shadow mode contract (D-047) — documentation status

- Default `notifications.delivery_mode=shadow` (product contract; not re-piloted live in Wave 10).
- Hot outbox rows are **not** enqueued until `live` **and** `TG_BOT_TOKEN` + `TG_NOTIFY_CHAT_ID` present.
- Switching to live does not flush historical shadow-eligible events that were never enqueued.
- Live Bot API delivery / Part B pilot: **NOT_RUN**.

## Windows operator smoke (product)

Checklist owner: `docs/engineering/WINDOWS_SMOKE_CHECKLIST.md`.

| Item | Wave 10 status |
|---|---|
| Desktop GOV smoke matrix (AT-GOV-011) | **`not_run`** — hosts not confirmed |
| `uv run pytest tests -q` on this capture | **`fail`** (see above) |
| Live migrate / backup / restore pilot | **NOT_RUN** (Wave 09 Part B blocked) |

Do **not** treat remediation wave executor PASS notes as substitute for green global suites.

## Known limitations (current)

- Full automated suite is **not collectable** under default pytest `pythonpath` because Wave 09 harness imports `tests.harness` while `pythonpath = ["src"]` only.
- Governance node test fixture count (221) drifted from live PRD counts (254).
- Authoritative hosted CI / required merge protection remain blocked pending hosting prerequisite.
- Real Telegram credentials are never used in automated tests; live Telegram proof requires owner-approved Part B.

## Rollback (ops)

1. Stop runtime (release process lock).
2. Restore last verified backup via `tld restore --backup …` only when runtime is stopped.
3. Re-run `tld integrity-check` and `tld migrate` as appropriate.
4. Keep `delivery_mode=shadow` until a live pilot is explicitly approved and re-validated.

## Explicit non-claims

- No PASS invented for failed commands.
- No commit, push, or merge performed.
- Wave 09 Part B live pilot not completed.
- Stale 2026-07-16 evidence numbers (e.g. “52 passed”) are **superseded** by this capture and must not be reused.
