# Wave 04 — Security boundary review (public/private)

- **Captured_at:** 2026-07-27T17:16:48+03:00
- **Reviewer:** Wave 04 sole executor (no separate security agent — override)
- **Verdict:** **PASS**
- **HIGH/CRITICAL findings:** **none**

## Scope

Public-only graph discovery edge expansion via TelegramGateway + SRC graph worker.

## Threats reviewed

| Threat | Result | Evidence |
|---|---|---|
| Private auto-join | **PASS** | No `JoinChannelRequest` / `ImportChatInviteRequest` in collector or graph modules; Fake `join_calls` ledger empty in tests |
| Invite-only / `t.me/+` / joinchat as candidates | **PASS** | `is_private_invite_ref` + extractors skip; integration asserts private invite not candidate |
| Linked discussion without public username | **PASS** | `_try_public_chat_snapshot` requires username; Fake `private=True` returns None |
| Inaccessible / inaccessible flag as candidate | **PASS** | Fake filters inaccessible recommendations/sample targets; resolve `GatewaySourceInaccessible` → `unsupported_source` |
| Unconfirmed username as public source | **PASS** | Forward origin without verifiable public username skipped; resolve required for text-only refs |
| Paid Stars / paid search in graph path | **PASS** | Graph path does not call `search_public_posts`; existing `allow_paid_stars=None` defense unchanged |
| Infinite crawl / depth bypass | **PASS** | `MAX_GRAPH_DEPTH=2`; depth-3 not resolved (`test_max_depth_two_not_three`) |
| Secret/session leakage via graph DTOs | **PASS** | Graph edges carry public usernames/snapshots only; no session paths |

## Residual / LOW notes (non-blocking)

- Telethon `sample_public_graph_edges` uses message text regex + optional forward chat username; entity-rich messages without text usernames may under-detect mentions (availability, not boundary breach).
- Recommendations depend on Telegram API returning chats; empty list when unsupported is safe fail-closed for expansion, not a join bypass.

## Conclusion

Public/private security boundary for Wave 04 graph discovery: **PASS**. No HIGH or CRITICAL findings.
