# Wave 02 — Acceptance Matrix (verifier)

**Captured_at:** 2026-07-27  
**Role:** verifier (fresh evidence; no product edits)

| # | Criterion (plan Gate) | Status | Evidence |
|---|---|---|---|
| G1 | Dismissed recurrence = 0 on deterministic multi-run fixture | **PASS** | `test_dismissed_recurrence_zero_multi_run_fixture` green in focused suite; spot re-run exit 0 (`assert recurrence == 0`) |
| G2 | Re-migrate does not change counts | **PASS** | `test_migration_remigrate_idempotent_counts_unchanged`: first==2, second==first after second `upgrade_head`; migration suite 3/3 pass |
| G3 | `ruff` green on touched paths | **PASS** | `uv run ruff check …` exit 0 — All checks passed |
| G4 | All focused tests green | **PASS** | Focused pytest exit 0 — **44 passed** in 8.22s |
| G5 | Verifier reviewed SQL/constraints → PASS | **PASS** | 003 creates/ensures `canonical_key NOT NULL` + `uq_dismissed_keyword_sources_canonical_key`; historical `_backfill_from_dismissed_snapshots`; temp DB PRAGMA unique + duplicate INSERT IntegrityError |

| # | Implementation AC (Wave 02 plan) | Status | Evidence |
|---|---|---|---|
| A1 | Migration empty DB → head | PASS | `test_migration_empty_db_reaches_suppress_head` + temp `upgrade_head` → `003_dismissed_keyword_suppress` |
| A2 | Populated 002 → historical dismiss backfill | PASS | `test_migration_populated_002_backfills_historical_dismiss`: 3 dismissed snaps → 2 suppress (`peer:500001`, `peer:500002`) |
| A3 | Unique canonical key | PASS | Model UniqueConstraint + temp SQLite `sqlite_autoindex_*` unique=1 on `canonical_key`; runtime UNIQUE fail on dup |
| A4 | Rename/alias → one suppress | PASS | Unit rename/alias + migration collapse peer 500001; promotion competing dismiss |
| A5 | Provisional → resolved peer merge | PASS | `test_unresolved_username_merges_into_resolved_peer_src034` / canonical identity suite |
| A6 | Competing dismiss retry → one row | PASS | `test_dismiss_during_competing_discovery_retry_one_suppress` (`canonical_key=peer:800001`) |
| A7 | Retention does not delete suppress | PASS | `test_retention_does_not_delete_suppress_ledger_sto017`; `retention.py` has no suppress purge references |
| A8 | Restart restores suppress from DB | PASS | `test_run_restart_restores_suppress_from_db` |
| A9 | Two providers → one identity | PASS | unit + `test_same_source_two_providers_one_suppress_identity` |
| A10 | Explicit reconsider / no implicit unsuppress | PASS | `test_reconsider_dismiss_suppress_is_explicit_src036` + `test_aggregation_does_not_implicitly_unsuppress` |
| A11 | Alembic head assert 003 | PASS | `test_at_sto_003_migration_head` (in storage_settings suite) |
| A12 | No live DB migrate | PASS | Commands used temp SQLite / pytest `tmp_path` only; live `%LOCALAPPDATA%\TelegramLeadDiscovery` observed exists, not touched |

## Wave02_gate

| Gate | Result |
|---|---|
| Wave02_gate | **PASS** |

All five plan Gate criteria G1–G5 PASS with fresh command exits.
