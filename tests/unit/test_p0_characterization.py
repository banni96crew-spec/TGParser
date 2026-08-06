"""Characterization barriers for the first decomposition phase."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from telegram_lead_discovery.collector.fake import make_source
from telegram_lead_discovery.collector.ports import GraphEdgeDTO
from telegram_lead_discovery.detection.seed import (
    ACTIVE_SEED_RULES,
    SEED_RULES,
    SEED_RULES_RU_MVP_2,
    SEED_RULES_RU_MVP_3,
    SEED_RULES_RU_MVP_4,
    catalog_canonical_json,
    catalog_checksum,
)
from telegram_lead_discovery.observability.discovery import (
    mark_discovery_healthy,
    note_transient_error,
    reset_discovery_observability,
)
from telegram_lead_discovery.observability.health import (
    HealthState,
    get_health_registry,
    reset_health_registry,
)
from telegram_lead_discovery.source_discovery.graph_discovery import (
    GraphBudget,
    canonical_key_for_snapshot,
    canonical_key_for_username,
    plan_edge_outcome,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    OpportunitySnapshotRecord,
    sort_opportunity_snapshots,
)
from telegram_lead_discovery.source_discovery.service import (
    InvalidUsernameError,
    normalize_username,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Test_Channel", "test_channel"),
        ("https://t.me/Test_Channel/?x=1", "test_channel"),
        ("http://t.me/Test_Channel#fragment", "test_channel"),
        ("t.me/Test_Channel/", "test_channel"),
        ("valid_name_123", "valid_name_123"),
    ],
)
def test_normalize_username_keeps_accepted_forms(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "abcd",
        "a" * 33,
        "name-with-dash",
        "two words",
        "https://t.me/+PrivateInvite",
        "t.me/joinchat/AbCdEf",
    ],
)
def test_normalize_username_rejects_invalid_or_private_refs(raw: str) -> None:
    with pytest.raises(InvalidUsernameError, match="^invalid_username:"):
        normalize_username(raw)


@pytest.mark.parametrize(
    ("rules", "expected_count", "expected_checksum", "first_rule", "last_rule"),
    [
        (
            SEED_RULES,
            43,
            "3f03d70f3577dd55c0df5da65eb877a518ef66e44344978766b2765f4aee7160",
            "NEG-SPAM-001",
            "SIG-SPC-002",
        ),
        (
            SEED_RULES_RU_MVP_2,
            48,
            "e1bd2fc98ec9feb138abb01182c4da5eee60e3b37d88a1c752dacac5d864c99b",
            "NEG-SPAM-001",
            "POS-DIR-005",
        ),
        (
            SEED_RULES_RU_MVP_3,
            58,
            "73efecbf35e0f5f79f20cbdaab8a8c35994e7dbfba2c69522193cec8b2c476e2",
            "NEG-SPAM-001",
            "NEG-VAC-006",
        ),
    ],
)
def test_seed_catalog_versions_are_byte_stable(
    rules,
    expected_count: int,
    expected_checksum: str,
    first_rule: str,
    last_rule: str,
) -> None:
    payload = json.loads(catalog_canonical_json(rules))

    assert len(rules) == expected_count
    assert len(payload) == expected_count
    assert catalog_checksum(rules) == expected_checksum
    assert payload[0]["stable_rule_id"] == first_rule
    assert payload[-1]["stable_rule_id"] == last_rule
    assert tuple(item["stable_rule_id"] for item in payload) == tuple(
        rule.stable_rule_id for rule in rules
    )
    assert all(item["flags"] == "IGNORECASE|FULLCASE|VERSION1" for item in payload)
    assert all(item["enabled"] is True for item in payload)


def test_active_seed_catalog_is_exactly_ru_mvp_4() -> None:
    assert ACTIVE_SEED_RULES is SEED_RULES_RU_MVP_4
    assert catalog_canonical_json() == catalog_canonical_json(SEED_RULES_RU_MVP_4)
    assert catalog_checksum() == catalog_checksum(SEED_RULES_RU_MVP_4)


def _opportunity(
    telegram_id: int,
    *,
    score: int,
    qualified: int,
    weeks: int,
    last_qualified_at: datetime,
) -> OpportunitySnapshotRecord:
    return OpportunitySnapshotRecord(
        run_id=1,
        source_id=None,
        source_telegram_id=telegram_id,
        username=f"source_{telegram_id}",
        title=f"Source {telegram_id}",
        source_type="channel",
        public_url=f"https://t.me/source_{telegram_id}",
        linked_parent_telegram_id=None,
        qualified_count=qualified,
        excluded_count=0,
        active_week_count=weeks,
        ecommerce_qualified_count=0,
        last_qualified_at=last_qualified_at,
        sample_message_count=0,
        sample_timestamps=(),
        score=score,
        band="review",
        score_components={},
        discovery_channels=("global_message",),
    )


def test_opportunity_sort_tie_break_is_deterministic() -> None:
    recent = datetime(2026, 7, 20, tzinfo=UTC)
    older = datetime(2026, 7, 10, tzinfo=UTC)
    snapshots = [
        _opportunity(2, score=60, qualified=3, weeks=4, last_qualified_at=recent),
        _opportunity(5, score=70, qualified=1, weeks=1, last_qualified_at=older),
        _opportunity(1, score=60, qualified=3, weeks=4, last_qualified_at=recent),
        _opportunity(3, score=60, qualified=3, weeks=5, last_qualified_at=older),
        _opportunity(4, score=60, qualified=4, weeks=1, last_qualified_at=older),
    ]

    ordered = sort_opportunity_snapshots(snapshots)

    assert [item.source_telegram_id for item in ordered] == [5, 4, 3, 1, 2]


def test_graph_canonical_keys_and_resolve_budget_are_stable() -> None:
    assert canonical_key_for_username("Mixed_CASE") == "username:mixed_case"
    assert canonical_key_for_snapshot(
        make_source(telegram_id=42, username="mixed_case")
    ) == "peer:42"

    unresolved_budget = GraphBudget(resolve_cap=0)
    unresolved = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=1,
        raw_reference="@needs_resolve",
        normalized_username="needs_resolve",
    )
    unresolved_result = plan_edge_outcome(
        unresolved,
        child_depth=1,
        budget=unresolved_budget,
    )
    assert unresolved_result.outcome == "budget_skipped"
    assert unresolved_budget.budget_skipped_total == 1
    assert unresolved_budget.resolved_canonical_keys == set()

    resolved_budget = GraphBudget(resolve_cap=0)
    resolved = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=1,
        raw_reference="@already_resolved",
        normalized_username="already_resolved",
        target=make_source(telegram_id=43, username="already_resolved"),
    )
    resolved_result = plan_edge_outcome(
        resolved,
        child_depth=1,
        budget=resolved_budget,
    )
    assert resolved_result.outcome == "candidate"
    assert resolved_budget.resolved_canonical_keys == {"peer:43"}


def test_reset_discovery_observability_clears_transient_window() -> None:
    reset_health_registry()
    reset_discovery_observability()
    clock = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    try:
        mark_discovery_healthy()
        for offset in range(3):
            note_transient_error(now=clock.replace(second=offset))
        assert get_health_registry().components["discovery"].state is HealthState.DEGRADED

        reset_discovery_observability()
        mark_discovery_healthy()
        note_transient_error(now=clock.replace(minute=1))
        note_transient_error(now=clock.replace(minute=1, second=1))

        assert get_health_registry().components["discovery"].state is HealthState.HEALTHY
    finally:
        reset_discovery_observability()
        reset_health_registry()
