# Wave 02 — executor-storage report

**Role:** executor-storage  
**Wave:** 02 — durable dismiss/suppress + canonical identity (STORAGE ONLY)  
**Captured_at:** 2026-07-27  
**Status:** `SUCCESS` (storage acceptance green; source-layer gaps remain)

## Goal

Implement storage/schema so migration + identity DB tests pass. Prefer zero
`source_discovery/*` edits (source executor owns those).

## Changes

| Path | Change |
|---|---|
| `src/telegram_lead_discovery/storage/models.py` | `DismissedKeywordSource`: `canonical_key` (unique), nullable `source_telegram_id`, `operator_trigger`, `version`; `before_insert`/`before_update` auto-derives `peer:<id>` / `username:<casefold>` for Wave-01 writers; added `DismissSuppressReconsideredEvent` audit table model |
| `src/telegram_lead_discovery/storage/alembic/versions/003_dismissed_keyword_suppress.py` | Complete 003: create/extend schema, unique `canonical_key`, nullable peer, reconsider audit table, **idempotent historical backfill** from `review_state=dismissed` snapshots collapsed by telegram peer |
| `src/telegram_lead_discovery/storage/dismissed_suppress.py` | **new** storage helpers: `upsert_dismiss_suppress`, `merge_provisional_into_peer`, `reconsider_dismiss_suppress`, key helpers |
| `.omc/artifacts/lead-discovery-remediation/wave-02/executor-storage-report.md` | this report |

## Not changed (by design)

- `source_discovery/*` — zero edits
- `retention.py` — already does not purge suppress ledger (AT-STO-017 retention test was already PASS)
- No live DB migrate
- No revision `004` (extended existing `003`)

## Verification

```powershell
uv run pytest tests/unit/test_keyword_search_aggregation.py tests/integration/test_opportunity_promotion.py tests/integration/test_storage_settings.py::test_at_sto_003_migration_head tests/integration/test_dismissed_suppress_migration.py tests/integration/test_canonical_identity_suppress.py -q --tb=line
```

**Result:** `5 failed, 34 passed` (was `9 failed, 30 passed` before storage work)

```powershell
uv run ruff check src/telegram_lead_discovery/storage/models.py src/telegram_lead_discovery/storage/dismissed_suppress.py src/telegram_lead_discovery/storage/alembic/versions/003_dismissed_keyword_suppress.py
```

**Result:** All checks passed

## PASS now (storage-owned / unblocked)

| Test | Notes |
|---|---|
| `test_at_sto_003_migration_head` | head = `003_dismissed_keyword_suppress` |
| `test_migration_empty_db_reaches_suppress_head` | empty ledger |
| `test_migration_populated_002_backfills_historical_dismiss` | suppress count = 2; keys `peer:500001`, `peer:500002` |
| `test_migration_remigrate_idempotent_counts_unchanged` | remigrate counts stable |
| `test_dismiss_during_competing_discovery_retry_one_suppress` | one row + `canonical_key=peer:800001` via model event |
| `test_same_source_two_providers_one_suppress_identity` | `canonical_key=peer:620001` |
| `test_retention_does_not_delete_suppress_ledger_sto017` | unchanged PASS |
| `test_run_restart_restores_suppress_from_db` | unchanged PASS |

## FAIL remaining (executor-source)

| Test | Failure | Owner |
|---|---|---|
| `test_rename_and_alias_collision_one_suppress_src033` | `ModuleNotFoundError: canonical_identity` | executor-source |
| `test_same_source_two_providers_one_identity_suppress` | `ModuleNotFoundError: peer_key` / canonical_identity | executor-source |
| `test_provisional_username_key_until_resolve_src034` | `ModuleNotFoundError: canonical_identity` | executor-source |
| `test_unresolved_username_merges_into_resolved_peer_src034` | missing `source_discovery.canonical_identity` + promotion wrappers | executor-source (may wrap `storage.dismissed_suppress`) |
| `test_reconsider_dismiss_suppress_is_explicit_src036` | missing `promotion.reconsider_dismiss_suppress` | executor-source (storage helper already exists) |

## Handoff for executor-source

1. Add `source_discovery/canonical_identity.py` with `peer_key`, `provisional_username_key`, `CanonicalSourceIdentity`, `collapse_identity_claims`, `merge_provisional_into_peer` (prefer wrapping `storage.dismissed_suppress`).
2. Wire `upsert_dismiss_suppress_for_identity` + `reconsider_dismiss_suppress` in `promotion.py` (wrap storage helpers; emit audit via `DismissSuppressReconsideredEvent`).
3. Optionally set `canonical_key` explicitly in `_upsert_dismissed_suppress_rule` (model event already covers peer path).

## Acceptance criteria

| Criterion | Status |
|---|---|
| Historical backfill in 003.upgrade (idempotent) | VERIFIED |
| Unique constraints / canonical key fields | VERIFIED |
| Provisional identity + merge at storage layer | VERIFIED (helpers landed; source wrappers pending) |
| Retention MUST NOT purge suppress ledger | VERIFIED (no retention change needed) |
| Re-migrate idempotent counts unchanged | VERIFIED |
| Migration FAIL → PASS | VERIFIED |
| Leave source-layer fails for next executor | VERIFIED |

## Compliance (executor-storage leaf)

- sequential-thinking: pass
- preflight-block: pass
- skills-used: `.cursor/skills/agent-preflight/SKILL.md`, `.cursor/skills/verify/SKILL.md`
- subagents-used: none
- hook-audit: not_run
- evidence-claim: not_run
