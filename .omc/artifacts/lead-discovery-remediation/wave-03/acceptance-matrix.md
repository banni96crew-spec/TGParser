# Wave 03 — Acceptance Matrix

**Captured_at:** 2026-07-27T17:00:23+03:00  
**Role:** executor (sole agent under EXECUTION_DISPATCH_OVERRIDE)  
**Gate:** PASS

| # | Criterion | Status | Evidence |
|---|---|---|---|
| G1 | Deterministic novelty ≥80% with sufficient pool | **PASS** | `test_five_run_novelty_fixture_ge_80_percent_and_dismissed_zero` — after_first ratios all ≥0.80 |
| G2 | Dismissed recurrence = 0 | **PASS** | Same fixture: `dismissed_recurrence == 0` for peer 42 across 5 runs |
| G3 | Suppressed recurrence / replacement after suppress | **PASS** | `test_replacement_fills_after_first_30_suppressed` — 100 acquired, 30 suppressed, fills quota 31..80 |
| G4 | `pool_exhausted` visible, not masked as success | **PASS** | `test_pool_exhaustion_visible_not_masked_as_success` — reason `no_unseen_after_suppress` |
| G5 | Score/eligibility decisions have machine-readable reasons | **PASS** | directory_only / needs_verification / required_service_profile_miss / profile_additional_exclusion / neutral_noise_sample in components |
| G6 | Weak hidden by default; available for audit | **PASS** | discovery UI default `review+promising`; `band=weak` opt-in; `band=all` shows both — `test_discovery_routes` assertions |
| G7 | Focused pytest green | **PASS** | 71 passed in 9.88s |
| G8 | ruff green on touched paths | **PASS** | All checks passed |

| # | Implementation AC (plan Wave 03) | Status | Evidence |
|---|---|---|---|
| A1 | Stages acquired/canonicalized/suppressed/qualified/presented | PASS | `merge_funnel_counters` + worker finalize counters |
| A2 | Provider cursor replacement after suppress | PASS | `acquire_with_replacement` + worker deep-verification filter |
| A3 | Cooldown 24h for presented non-dismissed; dismiss separate | PASS | `PresentationCooldownIndex` + `_load_presentation_cooldown` |
| A4 | Balanced query scheduling | PASS | `schedule_balanced_query_kinds` unit |
| A5 | Profile-specific deep verification queries | PASS | `select_deep_verification_queries` + worker uses it (not `post_queries[:5]`) |
| A6 | `additional_exclusions` + `required_service_profiles` with reasons | PASS | `match_additional_exclusion`, `apply_opportunity_eligibility`, build_opportunity wiring |
| A7 | `needs_verification` without evidence | PASS | linked_discussion_opportunity + eligibility gate |
| A8 | Directory-only cannot be review/promising | PASS | `directory_only_no_evidence` → weak ≤34 |
| A9 | Neutral noise sampling | PASS | `apply_neutral_noise_sample` |
| A10 | Persist components/evidence/reasons/provenance | PASS | score_components JSON includes eligibility_reasons; UI surfaces reasons |
| A11 | UI default review+promising; weak opt-in | PASS | discovery_routes + `_results.html` |

## Wave03_gate

| Gate | Result |
|---|---|
| Wave03_gate | **PASS** |

READY_FOR_WAVE_04
