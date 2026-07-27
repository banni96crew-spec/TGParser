# Wave 05 — Acceptance Matrix

**Captured_at:** 2026-07-27T17:28:29+03:00  
**Role:** executor (sole agent under EXECUTION_DISPATCH_OVERRIDE)  
**Gate:** PASS

| # | Criterion | Status | Evidence |
|---|---|---|---|
| G1 | Contract tests pass fake + adapter boundary | **PASS** | `tests/contract/test_fake_telegram_gateway.py` Wave 05 peer/history/live; `tests/adapter/test_telethon_peer_history.py` peer resolve |
| G2 | Backfill >100 messages paginates | **PASS** | `test_backfill_paginates_beyond_100` — 150 msgs → continued@100 + succeeded@50 |
| G3 | Replay create/edit/delete without duplicate current | **PASS** | `test_live_create_edit_delete_idempotent_no_dup` — 3 event types; replay create returns same row |
| G4 | Pause/disable stops ingest | **PASS** | `test_pause_stops_live_ingest` — lifecycle paused; live discarded; backfill job cancelled |
| G5 | No long SQLite write TX around network | **PASS** | `execute_backfill_job` fetch outside write; `persist_envelope_batch` ≤50; ValueError on oversized batch |
| G6 | DB source_id never Telethon entity (D-064) | **PASS** | Fake `resolved_entities` + adapter `iter_entities` assert ≠ source_id |
| G7 | FloodWait health + attempt not burned | **PASS** | `test_flood_wait_sets_retry_without_attempt_burn` |
| G8 | Focused pytest green | **PASS** | 59 passed (adapter+contract+collector+related) |
| G9 | ruff green on touched paths | **PASS** | All checks passed |
| G10 | Security redaction + session path ACL self-check | **PASS** | `security-boundary-review.md` |

| # | Implementation AC (plan Wave 05) | Status | Evidence |
|---|---|---|---|
| A1 | TelegramPeerRef on HistoryRequest | PASS | `ports.py` + COL-023 |
| A2 | Resolve via peer_id/access_hash or username | PASS | `_resolve_peer_entity` / fake `_entity_from_peer` |
| A3 | Backfill 14d/3000 + continuation | PASS | `BACKFILL_*` constants + continuation job enqueue |
| A4 | Persist batches ≤50 | PASS | `PERSIST_BATCH_SIZE=50` |
| A5 | Live DTO stable (peer_id, message_id) | PASS | `TelegramUpdateDTO.telegram_peer_id` + payload |
| A6 | Live filter monitoring only | PASS | `ingest_live_update` / `load_monitoring_peer_map` |
| A7 | Checkpoint after durable persist | PASS | `commit_checkpoint_with_envelope` same TX |
| A8 | Cancellation safe | PASS | cancel_requested / pause checks in finalize |

## Wave05_gate

| Gate | Result |
|---|---|
| Wave05_gate | **PASS** |

READY_FOR_WAVE_06
