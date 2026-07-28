"""Legacy import contracts required by the planned P0 decomposition."""

from __future__ import annotations

import importlib
import inspect

KEYWORD_MODULE = "telegram_lead_discovery.source_discovery.keyword_search"
SERVICE_MODULE = "telegram_lead_discovery.source_discovery.service"
GRAPH_MODULE = "telegram_lead_discovery.source_discovery.graph_discovery"
SEED_MODULE = "telegram_lead_discovery.detection.seed"
OBSERVABILITY_MODULE = "telegram_lead_discovery.observability.discovery"

KEYWORD_EXPORTS = (
    "AggregationResult",
    "AnnotatedSearchHit",
    "DetectFn",
    "DiscoveryChannel",
    "DismissedIdentityMatch",
    "DismissedKeywordSourceEntry",
    "DismissedKeywordSourceIndex",
    "ECOMMERCE_SERVICE_CODE",
    "EVIDENCE_WINDOW_DAYS",
    "EvidenceRecord",
    "HISTORY_SCAN_CAP_PER_RUN",
    "HISTORY_SCAN_CAP_PER_SOURCE",
    "MAX_DEEP_VERIFICATION_SOURCES",
    "MAX_EVIDENCE_PER_RUN",
    "MAX_NOISE_EVIDENCE_PER_RUN",
    "MAX_QUALIFIED_EVIDENCE_PER_RUN",
    "MAX_MESSAGES_PER_SOURCE",
    "QUALITY_DISTINCT_MIN",
    "QUALITY_WINDOW_DAYS",
    "OpportunitySnapshotRecord",
    "POOL_EXHAUSTED_REASON_CODES",
    "PRESENTATION_COOLDOWN",
    "PreliminarySourceCandidate",
    "PresentationCooldownIndex",
    "PresentedIdentityMatch",
    "PresentedKeywordSourceEntry",
    "PresentedKeywordSourceIndex",
    "RegistrySourceEntry",
    "ReplacementAcquisitionResult",
    "ResolvedSourceIdentity",
    "SourceRegistryIndex",
    "acquire_with_replacement",
    "aggregate_search_hits",
    "apply_neutral_noise_sample",
    "build_opportunity_from_evidence",
    "build_preliminary_candidates",
    "evidence_from_hit",
    "dismissed_telegram_ids",
    "is_registry_suppressed",
    "is_within_evidence_window",
    "linked_discussion_opportunity",
    "merge_evidence_duplicates",
    "merge_funnel_counters",
    "preliminary_rank_key",
    "presented_telegram_ids",
    "qualify_excerpt_text",
    "registry_telegram_ids",
    "resolve_dismissed_identity",
    "resolve_presented_identity",
    "resolve_source_identity",
    "select_sources_for_deep_verification",
    "sort_opportunity_snapshots",
)

OBSERVABILITY_EXPORTS = (
    "ALLOWED_DISCOVERY_STATES",
    "COMPONENT",
    "FORBIDDEN_METRIC_LABEL_KEYS",
    "NOVELTY_METRIC_NAMES",
    "ForbiddenMetricLabelError",
    "log_discovery",
    "log_query_progress",
    "log_run_finished",
    "mark_discovery_blocked",
    "mark_discovery_degraded",
    "mark_discovery_healthy",
    "mark_discovery_stopped",
    "note_flood_wait",
    "note_quota_skipped",
    "note_run_recovered",
    "note_session_fatal",
    "note_transient_error",
    "observe_discovery",
    "record_cooldown_suppressed",
    "record_dismissed_suppressed",
    "record_flood_wait_seconds",
    "record_funnel_observability",
    "record_novel_presented",
    "record_novelty_ratio",
    "record_pool_exhausted",
    "record_promotion",
    "record_qualified_evidence",
    "record_query_total",
    "record_registry_suppressed",
    "record_run_duration_seconds",
    "record_run_total",
    "record_score",
    "record_search_hits",
    "record_unique_sources",
    "record_verified_sources",
    "reset_discovery_observability",
    "set_discovery_health",
)

REQUIRED_SYMBOLS = {
    KEYWORD_MODULE: KEYWORD_EXPORTS,
    SERVICE_MODULE: (
        "USERNAME_RE",
        "REJECT_REASON_CODES",
        "InvalidUsernameError",
        "SourceLifecycleError",
        "CsvImportRowResult",
        "normalize_username",
        "add_manual_candidate",
        "import_csv",
        "approve_source",
        "reject_source",
        "reconsider_source",
        "pause_source",
        "resume_source",
        "disable_source",
        "list_sources",
    ),
    GRAPH_MODULE: (
        "JOB_TYPE_GRAPH_DISCOVERY",
        "ACTIVE_GRAPH_RUN_STATES",
        "TERMINAL_GRAPH_RUN_STATES",
        "MAX_GRAPH_DEPTH",
        "MAX_OUTGOING_EDGES_PER_SEED",
        "MAX_UNIQUE_GRAPH_CANDIDATES",
        "MAX_RESOLVE_OPS",
        "GRAPH_MESSAGE_SAMPLE_LIMIT",
        "GraphRunStartError",
        "StartGraphDiscoveryResult",
        "GraphQueueItem",
        "GraphCandidateResult",
        "GraphBudget",
        "is_private_invite_ref",
        "extract_public_usernames_from_text",
        "truncate_outgoing_edges",
        "filter_allowed_public_edges",
        "canonical_key_for_snapshot",
        "canonical_key_for_username",
        "plan_edge_outcome",
        "find_active_graph_run",
        "start_graph_discovery_run",
        "load_graph_seeds",
        "collect_edges_for_seed",
        "persist_graph_candidate",
        "load_registry_index",
    ),
    SEED_MODULE: (
        "RULE_FLAGS",
        "SeedRule",
        "SEED_RULES",
        "SEED_RULES_RU_MVP_2",
        "SEED_RULES_RU_MVP_3",
        "ACTIVE_SEED_RULES",
        "catalog_canonical_json",
        "catalog_checksum",
        "seed_ruleset_ru_mvp_1",
        "seed_ruleset_ru_mvp_2",
        "seed_ruleset_ru_mvp_3",
        "get_active_ruleset",
        "seed_active_ruleset",
    ),
    OBSERVABILITY_MODULE: (*OBSERVABILITY_EXPORTS, "_sanitize_log_fields"),
}

SIGNATURE_PARAMETERS = {
    (SERVICE_MODULE, "normalize_username"): ("value",),
    (KEYWORD_MODULE, "resolve_source_identity"): (
        "telegram_id",
        "username",
        "registry",
    ),
    (KEYWORD_MODULE, "aggregate_search_hits"): (
        "annotated_hits",
        "run_id",
        "scored_at",
        "registry",
        "dismissed",
        "presented",
        "detect_fn",
        "evidence_cap",
        "existing_evidence_count",
        "linked_parents",
    ),
    (GRAPH_MODULE, "plan_edge_outcome"): (
        "edge",
        "child_depth",
        "budget",
        "registry",
        "dismissed",
    ),
    (SEED_MODULE, "catalog_canonical_json"): ("rules",),
    (SEED_MODULE, "catalog_checksum"): ("rules",),
    (OBSERVABILITY_MODULE, "observe_discovery"): (
        "metric_name",
        "value",
        "labels",
        "now",
    ),
    (OBSERVABILITY_MODULE, "set_discovery_health"): (
        "state",
        "reason_code",
        "registry",
    ),
    (OBSERVABILITY_MODULE, "log_discovery"): (
        "event_code",
        "result",
        "duration_ms",
        "level",
        "correlation_id",
        "fields",
    ),
}


def test_legacy_modules_keep_required_symbols() -> None:
    for module_name, expected_names in REQUIRED_SYMBOLS.items():
        module = importlib.import_module(module_name)
        missing = [name for name in expected_names if not hasattr(module, name)]
        assert not missing, f"{module_name} lost legacy symbols: {missing}"


def test_explicit_export_lists_remain_stable() -> None:
    keyword = importlib.import_module(KEYWORD_MODULE)
    observability = importlib.import_module(OBSERVABILITY_MODULE)

    assert tuple(keyword.__all__) == KEYWORD_EXPORTS
    assert tuple(observability.__all__) == OBSERVABILITY_EXPORTS


def test_key_callable_parameter_order_remains_stable() -> None:
    for (module_name, callable_name), expected_parameters in SIGNATURE_PARAMETERS.items():
        callable_object = getattr(importlib.import_module(module_name), callable_name)
        actual_parameters = tuple(inspect.signature(callable_object).parameters)
        assert actual_parameters == expected_parameters
