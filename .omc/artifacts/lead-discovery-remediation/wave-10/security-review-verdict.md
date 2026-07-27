# Wave 10 — Security review verdict

- **Captured_at:** 2026-07-27T18:46:27+03:00
- **Reviewer:** SOLE Wave 10 agent
- **Overall risk:** **LOW**
- **Unresolved HIGH/CRITICAL:** **none**
- **Live Part B pilot:** **NOT_RUN** (blocked — HC-6 / owner approval)

## Threat matrix (fresh spot-check + prior wave evidence)

| Threat | Result | Evidence |
|---|---|---|
| Loopback-only HTTP bind | **PASS** | `main.py` rejects non-`127.0.0.1`; `assert_loopback_bind` in `runtime.py` |
| Telegram session / secrets in DB, logs, UI values | **PASS (spot)** | Session via `session_path()` inside Telethon adapter only; settings UI shows presence labels (`настроен` / `не настроен`); `redact_event` / `redact_mapping` on structured logs |
| CSRF on state-changing routes | **PASS (spot)** | `_csrf_or_403` on dashboard + discovery POSTs; templates carry `csrf_token` |
| Private auto-join / invite crawl | **PASS (prior + grep)** | No `JoinChannel` / `ImportChatInvite` in `src/`; Wave 04 security-boundary-review PASS |
| Paid Stars / paid search | **PASS (spot)** | `allow_paid_stars=None` in telethon search path; ports forbid Stars field (D-050) |
| Untrusted message text XSS | **PASS (spot / prior)** | Jinja defaults + Wave 08 gate “no secret/session/raw exceptions”; not re-browser-tested in Wave 10 |
| Backup excludes session | **PASS (contract prior)** | INF/SEC owner invariants; Wave 10 did not re-run live backup |
| Bot API credentials handling | **PASS (spot)** | `require_env("TG_BOT_TOKEN")` in notification worker; shadow mode still documented; no live Bot sends in Wave 10 |
| Wave 09 harness isolation | **Prior PASS / Wave 10 NOT re-verified** | Wave 09 notes: `LOCALAPPDATA`→tmp; fresh Wave 10 load command fails import — capacity proof not re-executed |

## Residual risks (≤ LOW, non-blocking for HIGH/CRITICAL bar)

1. **Wave 09 Part B live Windows pilot = NOT_RUN** — live migrate, live Telegram volume, dismiss recurrence/Jaccard unproven.
2. **Capacity/recovery harness not re-runnable** under default pytest in this capture — does not introduce a new secret leak, but weakens fresh proof of load isolation.
3. **Authoritative CI / merge protection blocked** (`ci-recompute` observe_only) — governance hosting prerequisite, not a product secret leak.
4. Multi-id delete completeness note from Wave 05 remains a completeness (not ACL) residual.

## Conclusion

Security overall risk **LOW**. No unresolved HIGH or CRITICAL findings on the reviewed remediation surface. Security bar alone would not block; **global verification FAIL** still blocks Wave 10 release gate.

**Commit/push/merge: NOT PERFORMED**
