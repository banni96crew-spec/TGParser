# Wave 04 — Acceptance Matrix

**Captured_at:** 2026-07-27T17:16:48+03:00  
**Role:** executor (sole agent under EXECUTION_DISPATCH_OVERRIDE)  
**Gate:** PASS

| # | Criterion | Status | Evidence |
|---|---|---|---|
| G1 | Fake graph fixture expands pool | **PASS** | `test_fake_graph_expands_pool_with_provenance` — rec + linked + mention candidates |
| G2 | Suppress / canonical dedupe | **PASS** | `test_dismiss_suppress_and_canonical_dedupe` + unit `test_canonical_dedupe_same_node_once` |
| G3 | Private/inaccessible not candidates | **PASS** | `test_private_and_inaccessible_not_candidates` + unit private filter |
| G4 | Provenance seed + edge type | **PASS** | Events carry `method` ∈ recommendation/linked_discussion/mention; `parent_source_id` + depth |
| G5 | Rate-limit / FloodWait degraded | **PASS** | `test_floodwait_degrades_with_cursor` — job `retry_wait`, run `running`+cursor |
| G6 | Cancellation | **PASS** | `test_cancellation_stops_graph_run` |
| G7 | depth=2 (not plan typo depth=1); caps 25/100 | **PASS** | `test_graph_budgets_match_prd_d017`; `test_max_depth_two_not_three` |
| G8 | Security: no HIGH/CRITICAL public/private | **PASS** | `security-boundary-review.md` |
| G9 | Focused pytest green | **PASS** | 66 passed |
| G10 | ruff green on touched paths | **PASS** | All checks passed |

| # | Implementation AC (plan Wave 04) | Status | Evidence |
|---|---|---|---|
| A1 | Allowed edges: linked, mention, t.me, forward_origin, recommendations | PASS | collect_edges_for_seed + Telethon GetChannelRecommendations |
| A2 | max 25 outgoing/seed; max 100 unique; no re-resolve same canonical | PASS | truncate_outgoing_edges + GraphBudget.resolved_canonical_keys |
| A3 | FloodWait → retryable/degraded, state preserved | PASS | `_park_graph_flood` + cursor_json |
| A4 | Wave 03 keyword not regressed | PASS | `test_keyword_discovery_wave03` included in gate (passed) |

## Wave04_gate

| Gate | Result |
|---|---|
| Wave04_gate | **PASS** |

READY_FOR_WAVE_05
