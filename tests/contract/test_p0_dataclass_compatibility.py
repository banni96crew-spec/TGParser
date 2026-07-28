"""DTO and dataclass field-order contracts required by the P0 decomposition."""

from __future__ import annotations

import importlib
from dataclasses import fields, is_dataclass

KEYWORD_MODULE = "telegram_lead_discovery.source_discovery.keyword_search"
SERVICE_MODULE = "telegram_lead_discovery.source_discovery.service"
GRAPH_MODULE = "telegram_lead_discovery.source_discovery.graph_discovery"
SEED_MODULE = "telegram_lead_discovery.detection.seed"

DATACLASS_FIELDS = {
    (KEYWORD_MODULE, "RegistrySourceEntry"): (
        "source_id",
        "telegram_id",
        "username_normalized",
        "aliases",
    ),
    (KEYWORD_MODULE, "ResolvedSourceIdentity"): (
        "canonical_telegram_id",
        "registry_source_id",
        "username_normalized",
        "matched_via",
    ),
    (KEYWORD_MODULE, "EvidenceRecord"): (
        "run_id",
        "source_telegram_id",
        "source_username",
        "source_title",
        "source_type",
        "telegram_message_id",
        "published_at",
        "permalink",
        "excerpt",
        "normalized_hash",
        "matched_query_ordinals",
        "discovery_channels",
        "detection_category",
        "is_qualified",
        "hard_exclusion",
        "hard_exclusion_rule_id",
        "service_profiles",
        "rule_set_checksum",
        "matched_rule_ids",
    ),
    (KEYWORD_MODULE, "OpportunitySnapshotRecord"): (
        "run_id",
        "source_id",
        "source_telegram_id",
        "username",
        "title",
        "source_type",
        "public_url",
        "linked_parent_telegram_id",
        "qualified_count",
        "excluded_count",
        "active_week_count",
        "ecommerce_qualified_count",
        "last_qualified_at",
        "sample_message_count",
        "sample_timestamps",
        "score",
        "band",
        "score_components",
        "discovery_channels",
        "review_state",
        "promoted_source_id",
        "dismiss_reason",
        "version",
        "truth_status",
        "verification_scanned_count",
        "verification_stop_reason",
    ),
    (KEYWORD_MODULE, "AggregationResult"): (
        "evidence",
        "opportunities",
        "budget_skipped_count",
        "window_skipped_count",
        "registry_suppressed_ids",
        "dismissed_suppressed_ids",
        "presented_suppressed_ids",
    ),
    (SERVICE_MODULE, "CsvImportRowResult"): (
        "line_no",
        "raw",
        "ok",
        "error_code",
        "source_id",
    ),
    (GRAPH_MODULE, "GraphCandidateResult"): (
        "outcome",
        "method",
        "depth",
        "raw_reference",
        "normalized_reference",
        "parent_source_id",
        "seed_telegram_id",
        "snapshot",
        "source_id",
        "evidence_message_id",
    ),
    (GRAPH_MODULE, "GraphBudget"): (
        "max_depth",
        "max_outgoing_edges",
        "candidate_cap",
        "resolve_cap",
        "resolves_used",
        "candidates_created",
        "merged_total",
        "depth_skipped_total",
        "budget_skipped_total",
        "unsupported_total",
        "invalid_total",
        "duplicate_in_run_total",
        "registry_suppressed_total",
        "dismissed_suppressed_total",
        "resolved_canonical_keys",
    ),
    (SEED_MODULE, "SeedRule"): (
        "stable_rule_id",
        "priority",
        "target",
        "dimension",
        "weight",
        "pattern",
        "explanation_code",
        "kind",
    ),
}


def test_public_dataclass_field_order_remains_stable() -> None:
    for (module_name, class_name), expected_fields in DATACLASS_FIELDS.items():
        cls = getattr(importlib.import_module(module_name), class_name)
        assert is_dataclass(cls), f"{module_name}.{class_name} is no longer a dataclass"
        assert tuple(field.name for field in fields(cls)) == expected_fields
