# Wave 07 — Acceptance Matrix

**Captured_at:** 2026-07-27T17:55:00+03:00  
**Role:** executor (sole agent under EXECUTION_DISPATCH_OVERRIDE)  
**Gate:** PASS

| # | Criterion | Status | Evidence |
|---|---|---|---|
| D1 | Seed creates immutable DB version at bootstrap only | **PASS** | `test_bootstrap_seed_only_creates_immutable_version`; runtime seed at startup remains bootstrap path |
| D2 | Runtime loader requires explicit version+checksum | **PASS** | `RuleCatalogLoader.load`; pipeline `_load_pinned_catalog` |
| D3 | Checksum mismatch → RULE_SET_INVALID, no SEED fallback | **PASS** | `test_loader_cache_and_mismatch`; `test_pipeline_mismatch_checksum_permanent` |
| D4 | Compile cache key = checksum | **PASS** | `test_compile_cache_keyed_by_checksum` |
| D5 | Byte-stable reprocess (same text+version) | **PASS** | `test_byte_stable_reprocess` via `stable_detection_payload` |
| D6 | Re-score creates new trace; old row immutable | **PASS** | `test_rescore_new_trace_preserves_old` |
| D7 | Pipeline pins rule_set_version_id+checksum | **PASS** | `test_pipeline_pins_version_no_seed_fallback` |
| C1 | Locked corpus ≥500 msgs from ≥10 sources | **PASS** | `locked_corpus.jsonl` size 520 / 12 sources |
| C2 | Train/val split present | **PASS** | calibration report train/val sizes |
| C3 | TP/FP/FN + confusion table | **PASS** | `calibration-report.json` category_metrics |
| C4 | hot precision ≥ 0.80 | **PASS** | val hot_precision = 1.0 |
| C5 | hot+warm precision ≥ 0.70 | **PASS** | val hot_warm_precision = 1.0 |
| C6 | purchase-intent/`direct_order` recall ≥ 0.75 | **PASS** | val purchase_intent_recall = 1.0 |
| C7 | No secrets/PII/raw live text in corpus | **PASS** | synthetic templates; secret-marker assert |
| G1 | Focused pytest green | **PASS** | 18 passed (`pytest-out.txt`) |
| G2 | ruff green on touched paths | **PASS** | All checks passed (`ruff-out.txt`) |

## Wave07_gate

| Gate | Result |
|---|---|
| Wave07_gate | **PASS** |

READY_FOR_WAVE_08
