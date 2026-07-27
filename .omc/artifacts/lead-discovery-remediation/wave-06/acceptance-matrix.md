# Wave 06 — Acceptance Matrix

**Captured_at:** 2026-07-27T17:46:30+03:00  
**Role:** executor (sole agent under EXECUTION_DISPATCH_OVERRIDE)  
**Gate:** PASS

| # | Criterion | Status | Evidence |
|---|---|---|---|
| L1 | Keyword/graph discovery scheduler loops start | **PASS** | `test_coordinator_starts_named_loops_not_deferred` |
| L2 | Collector job worker + live consumer | **PASS** | named_loops_running + E2E backfill/live |
| L3 | Processing claim + notification outbox | **PASS** | loops + E2E process/outbox |
| L4 | Startup + periodic reconciliation (15 min) | **PASS** | startup enqueue + `PERIODIC_RECONCILE_SECONDS == 900` |
| L5 | Health watchdog | **PASS** | watchdog loop + restart on injected failure |
| R1 | One loop failure ≠ kill all | **PASS** | `test_one_loop_failure_does_not_kill_siblings` |
| R2 | Jobs lease/claim restore | **PASS** | `test_startup_enqueues…recovers_stale_jobs` + E2E kill mid-batch |
| R3 | Single worker set on startup | **PASS** | `test_second_start_does_not_duplicate_workers` |
| R4 | Graceful shutdown | **PASS** | coordinator shutdown closes updates + stops loops |
| R5 | Notification disabled ≠ block leads | **PASS** | shadow loop healthy + pipeline lead tests |
| R6 | Outbox idempotent | **PASS** | E2E one outbox / one Bot call; outbox idempotency suite |
| H1 | Collector not permanent STOPPED/deferred | **PASS** | HEALTHY/`loops_running`; reason ≠ deferred |
| E1 | E2E temp DB + fake gateway full path | **PASS** | `test_wave06_full_pipeline_e2e_temp_db_fake_gateway` |
| G1 | Focused pytest green | **PASS** | 32 passed |
| G2 | ruff green on touched paths | **PASS** | All checks passed |

## Wave06_gate

| Gate | Result |
|---|---|
| Wave06_gate | **PASS** |

READY_FOR_WAVE_07
