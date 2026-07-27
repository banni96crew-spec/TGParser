# Wave 09 Part B — Live Windows Pilot Checklist (NOT EXECUTED)

Status: **BLOCKED / NOT_RUN** — requires explicit operator approval (HC-6).

Do **not** run any step below without owner go-ahead.

1. [ ] Operator approval recorded (date, who, scope).
2. [ ] Stop runtime; confirm process lock released.
3. [ ] `uv run tld integrity-check` on live DB.
4. [ ] `uv run tld backup`; verify backup exists + SHA-256.
5. [ ] Copy live DB to isolated path; migration dry-run there.
6. [ ] Compare historical dismiss counts before/after dry-run.
7. [ ] Apply migration to live DB (only after dry-run OK).
8. [ ] Start 3–5 approved monitoring sources for 30 minutes.
9. [ ] Verify backfill, live message, processing, UI, no duplicates, no secrets.
10. [ ] Scale 5 → 25 → 50 → 100 with health gate each step.
11. [ ] Run 5 discovery runs; compute recurrence / Jaccard / qualification distribution.

Rollback (if needed): stop runtime → keep failed diagnostics (no secrets) → restore from verified pre-migration backup → integrity-check → prior compatible version. Never downgrade over a live process.
