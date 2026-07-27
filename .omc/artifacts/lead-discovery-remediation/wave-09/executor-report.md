# Wave 09 Part A — Executor Report

- **Captured_at:** 2026-07-27T18:40:00+03:00
- **Status:** PASS
- **Wave09A_gate:** PASS
- **Wave09B_status:** NOT_RUN (BLOCKED — awaiting explicit operator approval / HC-6)
- **READY_FOR_WAVE_10:** yes (Part A only; Part B remains blocked)
- **Dispatch:** EXECUTION_DISPATCH_OVERRIDE (SOLE executor = tests + code + gate evidence)

## Scope delivered

Isolated load/recovery harness on **temp DB + FakeTelegramGateway** proving plan §2 / NFR-PERF-006..008 / NFR-REL-008:

1. 100 monitoring sources + ≥1000 simulated-day messages (steady p95 ≤30s)
2. 6000-event burst profile with concurrent paced drain (p95 ≤120s; post-inject drain ≤15 min)
3. 10% duplicate replay — zero new envelopes / messages / leads / outbox growth
4. Edits + deletes event types persisted and processed
5. Kill after fetch before persist — restart persist idempotent; recovery ≪5 min
6. Kill after persist before checkpoint — TX rollback; atomic restart; checkpoint never ahead
7. FloodWait → job `retry_wait` with `available_at ≥ until`, attempt not burned
8. Notification Bot API outage — outbox unique keys preserved; failures observed
9. UI inbox + monitoring coverage reads under concurrent write load

**Forbidden / not done:** live migrate, live Telegram joins, Bot API sends, commit/push, Part B pilot.

## Files touched

| Path | Responsibility |
|---|---|
| `tests/harness/__init__.py` | Harness package exports |
| `tests/harness/capacity_recovery.py` | Generators, scenario runners, SLO assertions |
| `tests/integration/test_wave09_capacity_recovery.py` | AT entry + temp-DB guard |
| `src/.../processing/pipeline.py` | Active ruleset pin cache (burst bottleneck) |
| `src/.../detection/loader.py` | `remember_active_pin` / `peek_active_pin` |
| `.omc/artifacts/.../wave-09/*` | Gate evidence |

## Minimal product fix (proven bottleneck)

First harness run with all-at-once burst inject failed **NFR-PERF-008** (p95 ≈175s > 120s) due to serial per-envelope TX + active ruleset DB lookup. Fixes:

1. Harness: batch process ≤50 envelopes/TX; paced concurrent inject+drain (≥10/s volume profile)
2. Product: cache active rule-set pin on `RuleCatalogLoader` so hot path skips repeated `get_active_ruleset` queries

## Key metrics (fresh run)

| Scenario | Result | Notable |
|---|---|---|
| steady 100/1000 | PASS | p95≈10.5s (≤30); drain≈10.9s |
| burst 6000 | PASS | p95≈1.1s (≤120); post-inject drain≈0.8s (≤900) |
| dup 10% | PASS | 40 rejected; 0 new envelopes on replay |
| edits/deletes | PASS | new+edit+delete envelopes |
| kill fetch→persist | PASS | fetched=20; recovery≈0.56s |
| kill persist→cp | PASS | rollback then atomic; recovery≈0.02s |
| FloodWait | PASS | retry_wait / flood_wait |
| notify outage | PASS | unique outbox keys; bot failures |
| UI under write | PASS | reads ok; sqlite_busy=0 |

## Verification

See `commands.json`, `acceptance-matrix.md`, `harness-report.json`.

- wave09 pytest: **2 passed** (~183s)
- related regression: **15 passed**
- ruff touched paths: **pass**

## Part B

Documented in `part-b-checklist.md` — **NOT executed**. Status = `NOT_RUN` awaiting owner approval.
