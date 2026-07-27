# Wave 02 — Rollback note (temp-DB only)

**Captured_at:** 2026-07-27  
**Scope:** Verifier evidence. **No live restore performed.**

## Plan rollback policy (authoritative)

From remediation plan Wave 02:

- Until live rollout: rollback is code/schema on **temp DB**.
- For live DB, downgrade is **not** primary recovery — use **pre-migration backup + stopped runtime restore**.

## What verifier did

| Action | Result |
|---|---|
| Temp SQLite empty upgrade → `003_dismissed_keyword_suppress` | OK under `%TEMP%\tld-wave02-verify-*\verify.sqlite` |
| Migration integration tests (tmp_path) | 3/3 PASS including remigrate idempotent |
| Live DB migrate / restore | **NOT RUN** (forbidden) |

## Live path status

- Observed: `%LOCALAPPDATA%\TelegramLeadDiscovery` **exists**.
- Verifier **did not** open, migrate, stamp, backup, or restore that tree.

## Temp-DB rollback procedure (if needed later)

1. Discard temp SQLite file(s) under `%TEMP%\tld-wave02-verify-*` (or pytest `tmp_path`).
2. Do **not** run `alembic downgrade` against live product DB as primary recovery.
3. For operator live rollback after a future approved migrate: stop runtime → restore pre-003 backup → verify revision stamp → restart.

## Code rollback (not executed by verifier)

If Wave 02 product code must be withdrawn before live migrate:

1. Revert Wave 02 commits / working tree changes for storage + source_discovery + tests.
2. Confirm alembic head returns to `002_keyword_source_discovery` only on **non-live** DBs.
3. Re-run focused suites to confirm green on prior head.

## Explicit non-actions

- No `upgrade_head` / Alembic against `%LOCALAPPDATA%\TelegramLeadDiscovery\...`
- No backup restore of live operator data
- No product code edits in this verifier pass
