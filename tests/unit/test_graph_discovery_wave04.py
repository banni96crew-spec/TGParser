"""Wave 04 — bounded public-only graph discovery (SRC-042 / AT-SRC-042)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GraphEdgeDTO,
    GraphSampleRequest,
    SourceRef,
)
from telegram_lead_discovery.source_discovery.graph_discovery import (
    MAX_GRAPH_DEPTH,
    MAX_OUTGOING_EDGES_PER_SEED,
    MAX_RESOLVE_OPS,
    MAX_UNIQUE_GRAPH_CANDIDATES,
    GraphBudget,
    extract_public_usernames_from_text,
    filter_allowed_public_edges,
    is_private_invite_ref,
    plan_edge_outcome,
    truncate_outgoing_edges,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    DismissedKeywordSourceEntry,
    DismissedKeywordSourceIndex,
    RegistrySourceEntry,
    SourceRegistryIndex,
)


def test_graph_budgets_match_prd_d017() -> None:
    assert MAX_GRAPH_DEPTH == 2
    assert MAX_OUTGOING_EDGES_PER_SEED == 25
    assert MAX_UNIQUE_GRAPH_CANDIDATES == 100
    assert MAX_RESOLVE_OPS == 25


def test_extract_mentions_and_public_links_skip_invites() -> None:
    text = (
        "see @devchat_ru and https://t.me/shop_leads plus "
        "https://t.me/+PrivateInvite and t.me/joinchat/AbCdEf"
    )
    found = extract_public_usernames_from_text(text)
    usernames = {u for u, _ in found}
    assert "devchat_ru" in usernames
    assert "shop_leads" in usernames
    assert all("+" not in u for u in usernames)
    assert "joinchat" not in usernames
    assert is_private_invite_ref("https://t.me/+PrivateInvite")
    assert is_private_invite_ref("t.me/joinchat/AbCdEf")


def test_outgoing_edge_cap_25() -> None:
    seed = 10
    edges = [
        GraphEdgeDTO(
            schema_version=1,
            edge_type="mention",
            seed_telegram_id=seed,
            raw_reference=f"@user{i:05d}",
            normalized_username=f"user{i:05d}",
        )
        for i in range(40)
    ]
    capped = truncate_outgoing_edges(edges, limit=25)
    assert len(capped) == 25


def test_depth_gt_2_skipped() -> None:
    budget = GraphBudget(max_depth=2)
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="public_link",
        seed_telegram_id=1,
        raw_reference="@depththree_src",
        normalized_username="depththree_src",
        target=make_source(telegram_id=99, username="depththree_src"),
    )
    result = plan_edge_outcome(edge, child_depth=3, budget=budget)
    assert result.outcome == "depth_skipped"
    assert budget.depth_skipped_total == 1


def test_private_target_filtered() -> None:
    private = make_source(telegram_id=2, username="hidden_x", accessible=False)
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="recommendation",
        seed_telegram_id=1,
        raw_reference="@hidden_x",
        normalized_username="hidden_x",
        target=private,
    )
    kept = filter_allowed_public_edges([edge])
    assert kept == ()


def test_dismissed_suppress_blocks_candidate() -> None:
    snap = make_source(telegram_id=42, username="dismissed_ch")
    dismissed = DismissedKeywordSourceIndex.from_entries(
        [
            DismissedKeywordSourceEntry(
                telegram_id=42,
                username_normalized="dismissed_ch",
            )
        ]
    )
    budget = GraphBudget()
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=1,
        raw_reference="@dismissed_ch",
        normalized_username="dismissed_ch",
        target=snap,
    )
    result = plan_edge_outcome(
        edge, child_depth=1, budget=budget, dismissed=dismissed
    )
    assert result.outcome == "dismissed_suppressed"


def test_canonical_dedupe_same_node_once() -> None:
    snap = make_source(telegram_id=7, username="once_only")
    budget = GraphBudget()
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="recommendation",
        seed_telegram_id=1,
        raw_reference="@once_only",
        normalized_username="once_only",
        target=snap,
    )
    first = plan_edge_outcome(edge, child_depth=1, budget=budget)
    second = plan_edge_outcome(edge, child_depth=1, budget=budget)
    assert first.outcome == "candidate"
    assert second.outcome == "duplicate_in_run"


def test_registry_merge_not_new_candidate() -> None:
    snap = make_source(telegram_id=8, username="known_src")
    registry = SourceRegistryIndex.from_entries(
        [
            RegistrySourceEntry(
                source_id=100,
                telegram_id=8,
                username_normalized="known_src",
            )
        ]
    )
    budget = GraphBudget()
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="linked_discussion",
        seed_telegram_id=1,
        raw_reference="@known_src",
        normalized_username="known_src",
        target=snap,
    )
    result = plan_edge_outcome(
        edge, child_depth=1, budget=budget, registry=registry
    )
    assert result.outcome == "merged"
    assert result.source_id == 100


def test_candidate_cap_budget_skip() -> None:
    budget = GraphBudget(candidate_cap=0)
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=1,
        raw_reference="@newcomer_x",
        normalized_username="newcomer_x",
        target=make_source(telegram_id=55, username="newcomer_x"),
    )
    result = plan_edge_outcome(edge, child_depth=1, budget=budget)
    assert result.outcome == "budget_skipped"


@pytest.mark.asyncio
async def test_fake_recommendations_public_only() -> None:
    gw = FakeTelegramGateway()
    public = make_source(telegram_id=20, username="rec_public")
    private = make_source(telegram_id=21, username="rec_private", accessible=False)
    gw.set_recommendations(10, [public, private])
    result = await gw.get_recommendations(
        SourceRef(schema_version=1, source_id=1, telegram_id=10), limit=10
    )
    assert [s.username for s in result] == ["rec_public"]
    assert gw.join_calls == []


@pytest.mark.asyncio
async def test_fake_sample_edges_and_floodwait() -> None:
    gw = FakeTelegramGateway()
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=10,
        raw_reference="@sampled_x",
        normalized_username="sampled_x",
        target=make_source(telegram_id=30, username="sampled_x"),
    )
    gw.set_graph_sample_edges(10, [edge])
    got = await gw.sample_public_graph_edges(
        GraphSampleRequest(
            schema_version=1,
            source=SourceRef(schema_version=1, source_id=1, telegram_id=10),
            message_limit=50,
        )
    )
    assert len(got) == 1
    assert got[0].edge_type == "mention"

    until = datetime.now(UTC) + timedelta(minutes=5)
    gw.set_flood_wait(until, "sample_public_graph_edges")
    with pytest.raises(GatewayFloodWait):
        await gw.sample_public_graph_edges(
            GraphSampleRequest(
                schema_version=1,
                source=SourceRef(schema_version=1, source_id=1, telegram_id=10),
            )
        )


@pytest.mark.asyncio
async def test_fake_inaccessible_not_recommended() -> None:
    gw = FakeTelegramGateway()
    snap = make_source(telegram_id=40, username="gone_chan")
    gw.set_recommendations(10, [snap])
    gw.mark_inaccessible(telegram_id=40)
    result = await gw.get_recommendations(
        SourceRef(schema_version=1, source_id=1, telegram_id=10), limit=5
    )
    assert result == []
