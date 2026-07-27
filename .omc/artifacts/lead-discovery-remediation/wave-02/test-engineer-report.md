# Wave 02 — test-engineer report

**Role:** test-engineer  
**Wave:** 02 — durable dismiss/suppress + canonical identity  
**Captured_at:** 2026-07-27  
**Status:** `TESTS_LANDED` (failing-first; product executors not yet green)

## Goal

Encode Wave 02 acceptance as failing-or-asserting tests before storage/source executors land. No broad `src/` product implementation.

## Strategy

- Behaviors: migration 003 empty/populated/idempotent; historical dismiss backfill; rename/alias → one suppress; provisional→peer merge; competing dismiss retry; retention immunity; restart restore; two-provider identity; dismissed recurrence = 0; explicit reconsider (no implicit unsuppress).
- Test levels: unit (`keyword_search` aggregation/index), integration (promotion, migration, identity/retention/restart), alembic head assert.

## Files changed

| Path | Change |
|---|---|
| `tests/unit/test_keyword_search_aggregation.py` | Wave 02 unit cases: rename/alias, two providers + `peer_key`, provisional key, multi-run recurrence=0, no implicit unsuppress |
| `tests/integration/test_opportunity_promotion.py` | Competing dismiss → one suppress + `canonical_key`; explicit `reconsider_dismiss_suppress` + audit event |
| `tests/integration/test_storage_settings.py` | Alembic head assert `002_*` → `003_dismissed_keyword_suppress` |
| `tests/integration/test_dismissed_suppress_migration.py` | **new** — empty migrate, populated-002 backfill, remigrate idempotent |
| `tests/integration/test_canonical_identity_suppress.py` | **new** — provisional merge, retention immunity, restart restore, two-provider suppress |
| `.omc/artifacts/lead-discovery-remediation/wave-02/test-engineer-report.md` | this report |

## Commands

```powershell
uv run pytest tests/unit/test_keyword_search_aggregation.py tests/integration/test_opportunity_promotion.py tests/integration/test_storage_settings.py::test_at_sto_003_migration_head tests/integration/test_dismissed_suppress_migration.py tests/integration/test_canonical_identity_suppress.py -q --tb=no
```

**Result:** `9 failed, 30 passed` (exit 1) — failures **expected** until executors implement Wave 02 product gaps.

## Failing tests (expected)

| Test | Failure | Blocks executor |
|---|---|---|
| `test_rename_and_alias_collision_one_suppress_src033` | `ModuleNotFoundError: canonical_identity` (after index match passes) | executor-source |
| `test_same_source_two_providers_one_identity_suppress` | `ModuleNotFoundError: peer_key` (after merge assert passes) | executor-source |
| `test_provisional_username_key_until_resolve_src034` | `ModuleNotFoundError: canonical_identity` | executor-source |
| `test_dismiss_during_competing_discovery_retry_one_suppress` | `canonical_key is None` (one-row suppress already holds) | executor-storage |
| `test_reconsider_dismiss_suppress_is_explicit_src036` | missing `reconsider_dismiss_suppress` / audit event model | executor-source + storage |
| `test_migration_populated_002_backfills_historical_dismiss` | suppress count `0 == 2` (003 creates table, no backfill) | executor-storage |
| `test_migration_remigrate_idempotent_counts_unchanged` | same — backfill missing so first count ≠ 2 | executor-storage |
| `test_unresolved_username_merges_into_resolved_peer_src034` | missing merge/upsert identity APIs | executor-source + storage |
| `test_same_source_two_providers_one_suppress_identity` | `canonical_key is None` (runtime suppress otherwise works) | executor-storage |

## Passing Wave 02 asserts (already green)

| Test | AC |
|---|---|
| `test_at_sto_003_migration_head` | head = `003_dismissed_keyword_suppress` |
| `test_migration_empty_db_reaches_suppress_head` | empty DB → head + empty ledger table |
| `test_dismissed_recurrence_zero_multi_run_fixture` | dismissed recurrence = 0 (deterministic unit) |
| `test_aggregation_does_not_implicitly_unsuppress` | aggregation cannot clear suppress membership |
| `test_retention_does_not_delete_suppress_ledger_sto017` | retention purge leaves suppress rows |
| `test_run_restart_restores_suppress_from_db` | `_load_dismissed_sources` restores from SQLite |

## AC mapping

| Plan / PRD AC | Test(s) | Status |
|---|---|---|
| Migration empty DB | `test_migration_empty_db_reaches_suppress_head` | PASS |
| Migration populated 002 + historical backfill | `test_migration_populated_002_backfills_historical_dismiss` | FAIL (expected) |
| Re-migrate idempotent | `test_migration_remigrate_idempotent_counts_unchanged` | FAIL (expected) |
| Rename / alias → one suppress | `test_rename_and_alias_collision_one_suppress_src033`, competing dismiss | FAIL (expected; index half green) |
| Unresolved → resolved peer merge | `test_unresolved_username_merges_into_resolved_peer_src034`, provisional unit | FAIL (expected) |
| Dismiss during competing retry | `test_dismiss_during_competing_discovery_retry_one_suppress` | FAIL (expected; needs `canonical_key`) |
| Retention does NOT delete suppress | `test_retention_does_not_delete_suppress_ledger_sto017` | PASS |
| Restart restores suppress from DB | `test_run_restart_restores_suppress_from_db` | PASS |
| Same source / two providers → one identity | unit + `test_same_source_two_providers_one_suppress_identity` | FAIL (expected; merge path green) |
| Dismissed recurrence = 0 multi-run | `test_dismissed_recurrence_zero_multi_run_fixture` | PASS |
| Reconsider explicit / no implicit unsuppress | `test_reconsider_dismiss_suppress_is_explicit_src036`, `test_aggregation_does_not_implicitly_unsuppress` | FAIL + PASS |
| Stale head assert 002→003 | `test_at_sto_003_migration_head` | PASS |
| SRC-033..036 / STO-017 / D-061/062 | covered by mapping above | encoded |

## Gaps for executors

1. **executor-storage:** extend `003_*` with historical dismissed snapshot backfill; add `canonical_key` (+ unique) on suppress ledger; nullable peer for provisional rows.
2. **executor-source:** add `source_discovery/canonical_identity.py` (`peer_key`, `provisional_username_key`, `collapse_identity_claims`, `merge_provisional_into_peer`); wire `reconsider_dismiss_suppress` + `DismissSuppressReconsidered` audit (not via `SourceDiscoveryEvent`).

## Forbidden checks

- No live DB touched.
- No secrets / session files.
- No broad product `src/` edits (tests + evidence only).

## Compliance (test-engineer leaf)

- sequential-thinking: pass
- preflight-block: pass
- skills-used: `.cursor/skills/agent-preflight/SKILL.md`, `.cursor/skills/verify/SKILL.md`
- subagents-used: none
- hook-audit: not_run
- evidence-claim: not_run
