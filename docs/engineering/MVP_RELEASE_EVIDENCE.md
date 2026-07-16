# MVP release evidence bundle

| Field | Value |
|---|---|
| Product | Telegram Lead Discovery |
| Schema | `schema_version=1` / Alembic `001_initial` |
| Owner gate | Phase 0 freeze + authorization 2026-07-16 |
| Status | `pass` — Phases 0–6 critical-path deliverables landed |

## Phase handoff summary

| Phase | Scope | Gate status | Evidence |
|---|---|---|---|
| 0 | Contract freeze D-039…D-047 | `pass` | `docs/prd/PHASE0_RESOLUTION_REGISTER.md`, `validate-prd.py` |
| 1 | SEC/INF/STO/SET/OBS foundation | `pass` | unit/integration foundation tests |
| 2 | SRC/COL ingestion sandbox | `pass` | fake gateway approve/backfill tests |
| 3 | PROC/DET/SCR calibration | `pass` | detection/scoring/pipeline tests |
| 4 | Shadow + UI | `pass` | `test_shadow_e2e.py`, `test_dashboard_ui.py`, keyset inbox/export |
| 5 | Hot notification pilot | `pass` | `test_notifications.py` fault injection / idempotency |
| 6 | Windows release hardening | `pass` | backup/restore/purge, `Register-TldTasks.ps1`, smoke checklist |

## Mandatory checks (recorded)

| Check | Result | Notes |
|---|---|---|
| `pytest tests` | `pass` — 52 passed | 2026-07-16 |
| `ruff check src tests` | `pass` after per-file E501 ignores for DET catalogs + wrap fixes | Phase 6 gate |
| `validate-prd.py` | `pass` | 195 req / 195 AT / 47 decisions |

## Shadow mode contract (D-047)

- Default `notifications.delivery_mode=shadow`
- Hot outbox rows are **not** enqueued until `live` **and** `TG_BOT_TOKEN` + `TG_NOTIFY_CHAT_ID` present
- Switching to live does not flush historical shadow-eligible events that were never enqueued

## Windows operator smoke (product)

1. `tld migrate`
2. `tld integrity-check`
3. `tld backup`
4. `tld start` → open `http://127.0.0.1:8765/`
5. Confirm inbox/settings/health without Bot delivery in shadow
6. `tld restore --backup <path>` only with stopped runtime
7. `deploy/windows/Register-TldTasks.ps1` for logon/start, 03:00 backup, 04:00 purge

## Known limitations

- Full `AT-*` catalog volume is not remapped ID-by-ID in automated suite; suites prove critical DoD journeys per phase.
- Real Telegram credentials are never used in automated tests.
- Desktop GOV smoke matrix may remain `not_run` until hosts confirmed (`WINDOWS_SMOKE_CHECKLIST.md`).

## Rollback

1. Stop runtime (release process lock).
2. Restore last verified backup via `tld restore --backup …`.
3. Re-run `tld integrity-check` and `tld migrate`.
4. Keep delivery_mode=`shadow` until pilot re-validated.
