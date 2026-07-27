# Wave 08 — Acceptance Matrix

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| UI-019 / AT-UI-019 | ReconsiderDismissSuppress requires CSRF + confirm | **PASS** | `test_at_ui_019_reconsider_suppress_requires_confirm` |
| UI-020 / AT-UI-020 | Run detail funnel + pool_exhausted + novelty_ratio | **PASS** | `test_at_ui_020_funnel_counters_visible` |
| UI-021 / AT-UI-021 | Default bands promising+review; weak opt-in | **PASS** | `test_at_ui_021_default_hides_weak` + Wave 03 regression |
| UI-022 / AT-UI-022 | Card identity/aliases/provenance/evidence/components/reasons | **PASS** | `test_at_ui_022_opportunity_card_fields` |
| UI-023 / AT-UI-023 | Lifecycle matrix; no Stars / send-to-author | **PASS** | `test_at_ui_023_lifecycle_actions_matrix` |
| UI-024 / AT-UI-024 | Monitoring coverage ≤100 checkpoint/backlog/errors | **PASS** | `test_at_ui_024_monitoring_coverage` |
| OBS-019 / AT-OBS-019 | Novelty/suppress metrics; forbidden labels absent | **PASS** | `test_at_obs_019_novelty_metrics_and_forbidden_labels` |
| OBS-020 / AT-OBS-020 | Named loops; collector not permanent STOPPED with creds+sources | **PASS** | `test_at_obs_020_named_loops_not_permanent_deferred` |
| OBS-021 / AT-OBS-021 | Capacity/latency/recovery metric names present | **PASS** | `test_at_obs_021_capacity_metric_names` |
| Gate | Empty/loading/error/degraded visible | **PASS** | run status template flags + health degraded |
| Gate | Weak not polluting default queue | **PASS** | AT-UI-021 |
| Gate | No secret/session/raw exceptions in templates | **PASS** | safe error helpers; secrets presence-only in settings |
| Gate | CSRF + 127.0.0.1 invariant | **PASS** | CSRF on POSTs; bind unchanged (loopback) |
| Gate | Route/integration tests green | **PASS** | 28 passed |
| Gate | Ruff green | **PASS** | `ruff-out.txt` |

## Verdict

**PASS → READY_FOR_WAVE_09**
