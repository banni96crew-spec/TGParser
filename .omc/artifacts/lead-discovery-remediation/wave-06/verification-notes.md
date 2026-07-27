# Wave 06 — Verification Notes

**Captured_at:** 2026-07-27T17:46:30+03:00

## Confirmed

- Named loops start with credentials via `RuntimeCoordinator.start`.
- Collector health uses `HEALTHY`/`DEGRADED`/`STARTING`/`BLOCKED` — not permanent `STOPPED` + `deferred` when credentials present.
- Injected collector loop failure leaves processing/discovery siblings alive; watchdog restarts the dead loop.
- E2E on temp SQLite + `FakeTelegramGateway`: approve → backfill → live create/edit/delete → process → one lead → optional hot outbox (idempotent) → pause blocks ingest → expired lease recovers.
- Shadow notifications: outbox loop remains up (`delivery_disabled`) without blocking lead creation.
- `tld run` is an alias of `start`.

## Inference

- Periodic reconciliation enqueue is scheduled at 15 minutes; covered by constant assertion + scheduler loop presence (not a real 15-minute wait in CI).

## Not run

- Live Telegram / product DB (forbidden).
- Full `uv run tld start` against a real Uvicorn bind in this gate (covered by coordinator unit/integration instead).

## Limitations

- Background loops + module write-lock require `reset_write_lock` between pytest event loops; production single-loop unaffected.
