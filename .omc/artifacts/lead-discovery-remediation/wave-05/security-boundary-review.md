# Wave 05 — Security boundary review (collector gateway)

- **Captured_at:** 2026-07-27T17:28:29+03:00
- **Reviewer:** Wave 05 sole executor (no separate security agent — override)
- **Verdict:** **PASS**
- **HIGH/CRITICAL findings:** **none**

## Scope

TelegramGateway peer resolution, backfill/live envelopes, session path usage in Telethon adapter.

## Threats reviewed

| Threat | Result | Evidence |
|---|---|---|
| DB `source_id` used as Telethon entity | **PASS** | Adapter `_resolve_peer_entity` / `get_message` refuse missing peer; tests assert entity ≠ source_id; Fake `resolved_entities` ledger |
| Session path / secrets in envelopes or logs | **PASS** | Envelopes store message text + peer ids only; `session_path()` used only inside adapter `connect`; no session string in DTO/payload |
| Secret keys leak via structured fields | **PASS** | Existing `redact_mapping` covers `session`, `api_hash`, `token`, `secret`; collector service does not log message body / secrets |
| Session file ACL / path handling | **PASS** | `session_path()` → `%LOCALAPPDATA%/TelegramLeadDiscovery/secrets/telegram.session`; connect uses env `TG_API_*` via `require_env`; stub mode when `telegram_ready` false (no credential invent) |
| Private auto-join via history/live | **PASS** | No JoinChannel / ImportChatInvite in Wave 05 paths; Fake `join_calls` unchanged empty |
| Account rotation after FloodWait | **PASS** | FloodWait → `retry_wait` until exact `until`; no second session |
| Long write TX holding lock across network | **PASS** | `execute_backfill_job` separates fetch vs `run_write` persist batches ≤50 |

## Residual / LOW notes (non-blocking)

- Live Telethon `iter_updates` queues NewMessage/Edited/Deleted; multi-id deletes currently emit first id only in `_event_to_update_dto` (completeness follow-up, not a secret/ACL breach).
- `access_hash` is not yet persisted on `TelegramSource`; resolve falls back to username or cached `get_entity(peer_id)` — safe public path, no ACL change.

## Conclusion

Collector Wave 05 security self-check (redaction + session path handling + peer misuse): **PASS**. No HIGH or CRITICAL findings.
