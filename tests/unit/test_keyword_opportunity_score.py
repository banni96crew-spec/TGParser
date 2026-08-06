"""Unit tests — keyword profile normalization, opportunity score, schema caps (SRC-017/018/025)."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import CheckConstraint

from telegram_lead_discovery.source_discovery.keyword_profiles import (
    MAX_DIRECTORY_QUERIES,
    MAX_EVIDENCE_EXCERPT_CODEPOINTS,
    MAX_POST_QUERIES,
    MAX_QUERY_LEN,
    MIN_POST_QUERIES,
    MIN_QUERY_LEN,
    SEED_ADDITIONAL_EXCLUSIONS,
    SEED_DIRECTORY_QUERIES,
    SEED_POST_QUERIES,
    SEED_PROFILE_NAME,
    SEED_PROFILE_VERSION,
    ProfileValidationError,
    build_seed_normalized_profile,
    normalize_profile_queries,
    normalize_query,
    seed_profile_checksum,
    truncate_evidence_excerpt,
)
from telegram_lead_discovery.source_discovery.opportunity_score import (
    OpportunityRankKey,
    active_weeks,
    clamp_score,
    ecommerce_component,
    noise_penalty_component,
    qualified_component,
    recency_component,
    regularity_component,
    score_opportunity,
    sort_opportunities,
)
from telegram_lead_discovery.storage.models import (
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)


def test_normalize_query_trim_and_casefold() -> None:
    assert normalize_query("  Нужен Разработчик  ") == "нужен разработчик"


def test_profile_normalization_happy_path() -> None:
    normalized = normalize_profile_queries(
        post_queries=["  Нужен сайт  ", "ищу бота"],
        directory_queries=["Ecommerce"],
        additional_exclusions=[" Курс "],
        source_scope="groups",
    )
    assert normalized.post_queries == ("нужен сайт", "ищу бота")
    assert normalized.directory_queries == ("ecommerce",)
    assert normalized.additional_exclusions == ("курс",)
    assert normalized.source_scope == "groups"


def test_profile_rejects_casefold_duplicates() -> None:
    with pytest.raises(ProfileValidationError, match="duplicate_query"):
        normalize_profile_queries(
            post_queries=["Нужен сайт", "  нужен сайт  "],
        )


def test_profile_query_limits() -> None:
    with pytest.raises(ProfileValidationError, match="post_queries_count_out_of_range"):
        normalize_profile_queries(post_queries=[])

    too_many_posts = [f"query{i:02d}xx" for i in range(MAX_POST_QUERIES + 1)]
    with pytest.raises(ProfileValidationError, match="post_queries_count_out_of_range"):
        normalize_profile_queries(post_queries=too_many_posts)

    too_many_dirs = [f"dir{i:02d}xx" for i in range(MAX_DIRECTORY_QUERIES + 1)]
    with pytest.raises(ProfileValidationError, match="directory_queries_count_out_of_range"):
        normalize_profile_queries(
            post_queries=["нужен сайт"],
            directory_queries=too_many_dirs,
        )


def test_profile_query_length_bounds() -> None:
    short = "ab"
    assert len(short) < MIN_QUERY_LEN
    with pytest.raises(ProfileValidationError, match="query_length_out_of_range"):
        normalize_profile_queries(post_queries=[short])

    long_q = "x" * (MAX_QUERY_LEN + 1)
    with pytest.raises(ProfileValidationError, match="query_length_out_of_range"):
        normalize_profile_queries(post_queries=[long_q])


def test_seed_profile_checksum_stable_and_valid() -> None:
    seed = build_seed_normalized_profile()
    assert SEED_PROFILE_NAME == "ecommerce-development-ru"
    assert SEED_PROFILE_VERSION == 3
    assert len(SEED_POST_QUERIES) == 18
    assert MIN_POST_QUERIES <= len(seed.post_queries) <= MAX_POST_QUERIES
    assert len(SEED_DIRECTORY_QUERIES) == len(seed.directory_queries) == 10
    assert len(SEED_ADDITIONAL_EXCLUSIONS) == len(seed.additional_exclusions)
    checksum = seed_profile_checksum()
    assert len(checksum) == 64
    assert checksum == seed_profile_checksum()
    assert checksum == checksum.lower()


def test_evidence_excerpt_cap_240_codepoints() -> None:
    raw = "я" * (MAX_EVIDENCE_EXCERPT_CODEPOINTS + 25)
    clipped = truncate_evidence_excerpt(raw)
    assert len(clipped) == MAX_EVIDENCE_EXCERPT_CODEPOINTS
    assert clipped == raw[:MAX_EVIDENCE_EXCERPT_CODEPOINTS]
    assert truncate_evidence_excerpt("short") == "short"


def test_schema_excerpt_and_score_constraints() -> None:
    excerpt_col = SourceDiscoveryEvidence.__table__.c.excerpt
    assert excerpt_col.type.length == 240

    score_col = SourceOpportunitySnapshot.__table__.c.score
    assert score_col is not None
    check_names = {
        c.name
        for c in SourceOpportunitySnapshot.__table__.constraints
        if isinstance(c, CheckConstraint)
    }
    assert "ck_opportunity_score_0_100" in check_names


def test_schema_migration_revision_id() -> None:
    mod = importlib.import_module(
        "telegram_lead_discovery.storage.alembic.versions.002_keyword_source_discovery"
    )
    assert mod.revision == "002_keyword_source_discovery"
    assert mod.down_revision == "001_initial"


def test_score_components_and_bands() -> None:
    scored_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    last = scored_at - timedelta(days=2)
    weeks = [
        scored_at - timedelta(days=2),
        scored_at - timedelta(days=9),
        scored_at - timedelta(days=16),
        scored_at - timedelta(days=23),
    ]
    result = score_opportunity(
        qualified_count=5,
        excluded_count=1,
        ecommerce_qualified_count=3,
        last_qualified_at=last,
        scored_at=scored_at,
        qualified_timestamps=weeks,
    )
    assert result.components.qualified == 40
    assert result.components.regularity == 25
    assert result.components.ecommerce == 15
    assert result.components.recency == 15
    assert result.components.noise_penalty == noise_penalty_component(
        qualified_count=5, excluded_count=1
    )
    expected = clamp_score(40 + 25 + 15 + 15 - result.components.noise_penalty)
    assert result.total == expected
    assert result.band == "promising"
    assert result.active_week_count == 4


def test_each_score_component_table() -> None:
    assert [qualified_component(n) for n in range(0, 7)] == [0, 8, 16, 24, 32, 40, 40]
    assert [regularity_component(n) for n in range(0, 6)] == [0, 8, 14, 20, 25, 25]
    assert ecommerce_component(0) == 0
    assert ecommerce_component(3) == 15
    assert ecommerce_component(5) == 20
    assert ecommerce_component(99) == 20

    now = datetime(2026, 7, 23, tzinfo=UTC)
    assert recency_component(now - timedelta(days=0), scored_at=now) == 15
    assert recency_component(now - timedelta(days=3), scored_at=now) == 15
    assert recency_component(now - timedelta(days=4), scored_at=now) == 10
    assert recency_component(now - timedelta(days=7), scored_at=now) == 10
    assert recency_component(now - timedelta(days=8), scored_at=now) == 5
    assert recency_component(now - timedelta(days=14), scored_at=now) == 5
    assert recency_component(now - timedelta(days=15), scored_at=now) == 0
    assert recency_component(None, scored_at=now) == 0

    assert noise_penalty_component(qualified_count=0, excluded_count=0) == 0
    assert noise_penalty_component(qualified_count=0, excluded_count=10) == 30
    assert noise_penalty_component(qualified_count=1, excluded_count=1) == 15


def test_clamp_score_0_100() -> None:
    assert clamp_score(-40) == 0
    assert clamp_score(0) == 0
    assert clamp_score(100) == 100
    assert clamp_score(140) == 100

    # High noise + zero positives clamps to 0.
    result = score_opportunity(
        qualified_count=0,
        excluded_count=10,
        ecommerce_qualified_count=0,
        last_qualified_at=None,
        scored_at=datetime(2026, 7, 23, tzinfo=UTC),
        active_week_count=0,
    )
    assert result.total == 0
    assert result.band == "weak"
    assert result.components.noise_penalty == 30


def test_active_weeks_distinct_iso_weeks() -> None:
    # Monday 2026-06-01 and Sunday 2026-06-07 same ISO week; next Monday new week.
    w1a = datetime(2026, 6, 1, 10, tzinfo=UTC)
    w1b = datetime(2026, 6, 7, 10, tzinfo=UTC)
    w2 = datetime(2026, 6, 8, 10, tzinfo=UTC)
    assert active_weeks([w1a, w1b, w2]) == 2
    assert active_weeks([]) == 0


def test_deterministic_tie_break() -> None:
    t_newer = datetime(2026, 7, 20, tzinfo=UTC)
    t_older = datetime(2026, 7, 10, tzinfo=UTC)
    items = [
        OpportunityRankKey(50, 3, 2, t_older, telegram_id=200),
        OpportunityRankKey(50, 3, 2, t_newer, telegram_id=100),
        OpportunityRankKey(50, 3, 3, t_older, telegram_id=50),
        OpportunityRankKey(60, 1, 1, t_older, telegram_id=9),
        OpportunityRankKey(50, 4, 1, t_older, telegram_id=1),
        OpportunityRankKey(50, 3, 2, t_newer, telegram_id=90),
    ]
    ordered = sort_opportunities(items)
    assert [i.telegram_id for i in ordered] == [9, 1, 50, 90, 100, 200]
