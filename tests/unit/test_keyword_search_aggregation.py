"""Unit tests — keyword search evidence aggregation and opportunity scoring (SRC-021..025)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.collector.ports import SearchMessageHitDTO, SourceSnapshot
from telegram_lead_discovery.detection.engine import DetectionResult
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    MAX_EVIDENCE_EXCERPT_CODEPOINTS,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    MAX_DEEP_VERIFICATION_SOURCES,
    MAX_EVIDENCE_PER_RUN,
    AnnotatedSearchHit,
    EvidenceRecord,
    PreliminarySourceCandidate,
    RegistrySourceEntry,
    SourceRegistryIndex,
    aggregate_search_hits,
    build_opportunity_from_evidence,
    build_preliminary_candidates,
    linked_discussion_opportunity,
    merge_evidence_duplicates,
    qualify_excerpt_text,
    resolve_source_identity,
    select_sources_for_deep_verification,
)


def _source(
    telegram_id: int,
    *,
    username: str = "devchat",
    title: str = "Dev Chat",
    source_type: str = "megagroup",
) -> SourceSnapshot:
    return SourceSnapshot(
        schema_version=1,
        telegram_id=telegram_id,
        username=username,
        title=title,
        source_type=source_type,  # type: ignore[arg-type]
        public_url=f"https://t.me/{username}",
    )


def _hit(
    *,
    telegram_id: int,
    message_id: int,
    excerpt: str,
    published_at: datetime,
    username: str = "devchat",
    title: str = "Dev Chat",
    source_type: str = "megagroup",
) -> SearchMessageHitDTO:
    return SearchMessageHitDTO(
        schema_version=1,
        source=_source(
            telegram_id,
            username=username,
            title=title,
            source_type=source_type,
        ),
        telegram_message_id=message_id,
        published_at=published_at,
        permalink=f"https://t.me/{username}/{message_id}",
        excerpt=excerpt,
    )


def _fake_detect(category: str, *, is_lead: bool, hard: bool = False) -> DetectionResult:
    return DetectionResult(
        category=category,
        is_lead=is_lead,
        hard_exclusion=hard,
        hard_exclusion_rule_id="EXCL-001" if hard else None,
        matched_rules=(),
        service_profiles=("ecommerce",) if is_lead else (),
        timed_out_rule_ids=(),
        signals={},
        explanation_codes=(),
        duration_ms=1,
        rule_set_checksum="abc123",
    )


def test_excerpt_cap_240_and_no_author_fields() -> None:
    raw = "я" * (MAX_EVIDENCE_EXCERPT_CODEPOINTS + 40)
    excerpt, digest, detection = qualify_excerpt_text(
        raw,
        detect_fn=lambda _t: _fake_detect("irrelevant", is_lead=False),
    )
    assert len(excerpt) == MAX_EVIDENCE_EXCERPT_CODEPOINTS
    assert len(digest) == 64
    assert detection.category == "irrelevant"
    # EvidenceRecord fields must not include author metadata.
    fields = set(EvidenceRecord.__dataclass_fields__)
    assert "author_peer_id" not in fields
    assert "author_username" not in fields
    assert "author_display_name" not in fields
    assert "media" not in fields


def test_dedupe_same_telegram_message_merges_queries() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    hit = _hit(
        telegram_id=1001,
        message_id=55,
        excerpt="нужен разработчик сайта",
        published_at=now - timedelta(days=1),
    )
    result = aggregate_search_hits(
        [
            AnnotatedSearchHit(hit, query_ordinal=1, discovery_channel="global_message"),
            AnnotatedSearchHit(hit, query_ordinal=3, discovery_channel="public_posts"),
        ],
        run_id=7,
        scored_at=now,
        detect_fn=lambda _t: _fake_detect("direct_order", is_lead=True),
    )
    assert len(result.evidence) == 1
    ev = result.evidence[0]
    assert ev.matched_query_ordinals == (1, 3)
    assert set(ev.discovery_channels) == {"global_message", "public_posts"}
    assert len(result.opportunities) == 1
    assert result.opportunities[0].sample_message_count == 1
    assert result.opportunities[0].qualified_count == 1


def test_identity_order_username_maps_to_registry_telegram_id() -> None:
    registry = SourceRegistryIndex.from_entries(
        [
            RegistrySourceEntry(
                source_id=42,
                telegram_id=9001,
                username_normalized="shopdevs",
                aliases=("oldshop",),
            )
        ]
    )
    via_user = resolve_source_identity(
        telegram_id=555,
        username="shopdevs",
        registry=registry,
    )
    assert via_user.canonical_telegram_id == 9001
    assert via_user.registry_source_id == 42
    assert via_user.matched_via == "username"

    via_alias = resolve_source_identity(
        telegram_id=556,
        username="oldshop",
        registry=registry,
    )
    assert via_alias.canonical_telegram_id == 9001
    assert via_alias.matched_via == "alias"

    via_tid = resolve_source_identity(
        telegram_id=9001,
        username="other",
        registry=registry,
    )
    assert via_tid.matched_via == "registry_telegram_id"
    assert via_tid.registry_source_id == 42


def test_aggregate_merges_sources_via_alias_identity() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    registry = SourceRegistryIndex.from_entries(
        [
            RegistrySourceEntry(
                source_id=10,
                telegram_id=100,
                username_normalized="canonical",
                aliases=("aliasname",),
            )
        ]
    )
    hit_a = _hit(
        telegram_id=100,
        message_id=1,
        excerpt="нужен интернет-магазин",
        published_at=now - timedelta(days=2),
        username="canonical",
    )
    hit_b = _hit(
        telegram_id=999,
        message_id=2,
        excerpt="нужен telegram бот",
        published_at=now - timedelta(days=1),
        username="aliasname",
    )
    result = aggregate_search_hits(
        [
            AnnotatedSearchHit(hit_a, 1, "global_message"),
            AnnotatedSearchHit(hit_b, 2, "global_message"),
        ],
        run_id=1,
        scored_at=now,
        registry=registry,
        detect_fn=lambda _t: _fake_detect("direct_order", is_lead=True),
    )
    assert len(result.opportunities) == 1
    opp = result.opportunities[0]
    assert opp.source_telegram_id == 100
    assert opp.source_id == 10
    assert opp.sample_message_count == 2
    assert opp.qualified_count == 2


def test_window_and_budget_skips() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    fresh = _hit(
        telegram_id=1,
        message_id=1,
        excerpt="нужен сайт",
        published_at=now - timedelta(days=5),
    )
    stale = _hit(
        telegram_id=1,
        message_id=2,
        excerpt="нужен сайт",
        published_at=now - timedelta(days=45),
    )
    result = aggregate_search_hits(
        [
            AnnotatedSearchHit(fresh, 1, "global_message"),
            AnnotatedSearchHit(stale, 1, "global_message"),
        ],
        run_id=1,
        scored_at=now,
        evidence_cap=1,
        detect_fn=lambda _t: _fake_detect("irrelevant", is_lead=False),
    )
    assert result.window_skipped_count == 1
    assert len(result.evidence) == 1

    extras = [
        AnnotatedSearchHit(
            _hit(
                telegram_id=2,
                message_id=i,
                excerpt=f"query text {i}",
                published_at=now - timedelta(hours=i),
            ),
            1,
            "global_message",
        )
        for i in range(3)
    ]
    capped = aggregate_search_hits(
        extras,
        run_id=1,
        scored_at=now,
        evidence_cap=2,
        detect_fn=lambda _t: _fake_detect("irrelevant", is_lead=False),
    )
    assert len(capped.evidence) == 2
    assert capped.budget_skipped_count == 1
    assert MAX_EVIDENCE_PER_RUN == 500


def test_opportunity_score_from_evidence() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    source = _source(77)
    evidence = [
        EvidenceRecord(
            run_id=1,
            source_telegram_id=77,
            source_username="devchat",
            source_title="Dev Chat",
            source_type="megagroup",
            telegram_message_id=i,
            published_at=now - timedelta(days=d),
            permalink=None,
            excerpt="нужен интернет-магазин",
            normalized_hash=f"h{i}",
            matched_query_ordinals=(1,),
            discovery_channels=("global_message",),
            detection_category="direct_order",
            is_qualified=True,
            hard_exclusion=False,
            hard_exclusion_rule_id=None,
            service_profiles=("ecommerce",),
            rule_set_checksum="x",
        )
        for i, d in enumerate((1, 8, 15, 22), start=1)
    ]
    evidence.append(
        EvidenceRecord(
            run_id=1,
            source_telegram_id=77,
            source_username="devchat",
            source_title="Dev Chat",
            source_type="megagroup",
            telegram_message_id=99,
            published_at=now - timedelta(days=3),
            permalink=None,
            excerpt="курс python",
            normalized_hash="hexcl",
            matched_query_ordinals=(2,),
            discovery_channels=("global_message",),
            detection_category="vacancy",
            is_qualified=False,
            hard_exclusion=True,
            hard_exclusion_rule_id="EXCL",
            service_profiles=(),
            rule_set_checksum="x",
        )
    )
    opp = build_opportunity_from_evidence(
        run_id=1,
        source=source,
        evidence=evidence,
        scored_at=now,
    )
    assert opp.qualified_count == 4
    assert opp.excluded_count == 1
    assert opp.ecommerce_qualified_count == 4
    assert opp.active_week_count == 4
    assert opp.band in ("promising", "review", "weak")
    assert 0 <= opp.score <= 100
    assert opp.score_components["qualified"] == 32
    assert opp.review_state == "unreviewed"
    assert "author" not in opp.score_components_json().lower()


def test_linked_discussion_separate_opportunity() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    discussion = _source(
        200,
        username="channelchat",
        title="Channel Chat",
        source_type="megagroup",
    )
    opp = linked_discussion_opportunity(
        run_id=3,
        parent_telegram_id=100,
        discussion=discussion,
        scored_at=now,
    )
    assert opp.linked_parent_telegram_id == 100
    assert opp.source_telegram_id == 200
    assert opp.discovery_channels == ("linked_discussion",)
    assert opp.score == 0
    assert opp.band == "weak"


def test_preliminary_ranking_and_deep_cap() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    candidates = [
        PreliminarySourceCandidate(
            telegram_id=1,
            source_type="channel",
            title="A",
            username="a",
            distinct_query_count=1,
            seed_evidence_count=1,
            directory_title_match=False,
            is_linked_discussion=False,
            freshest_evidence_at=now,
            discovery_channels=("global_message",),
        ),
        PreliminarySourceCandidate(
            telegram_id=2,
            source_type="megagroup",
            title="Ecommerce Devs",
            username="b",
            distinct_query_count=5,
            seed_evidence_count=3,
            directory_title_match=True,
            is_linked_discussion=True,
            freshest_evidence_at=now,
            discovery_channels=("directory", "global_message"),
        ),
        PreliminarySourceCandidate(
            telegram_id=3,
            source_type="megagroup",
            title="C",
            username="c",
            distinct_query_count=5,
            seed_evidence_count=3,
            directory_title_match=False,
            is_linked_discussion=False,
            freshest_evidence_at=now - timedelta(days=10),
            discovery_channels=("global_message",),
        ),
    ]
    selected = select_sources_for_deep_verification(candidates, limit=2)
    assert [c.telegram_id for c in selected] == [2, 3]
    assert MAX_DEEP_VERIFICATION_SOURCES == 25

    many = [
        PreliminarySourceCandidate(
            telegram_id=i,
            source_type="channel",
            title=str(i),
            username=f"u{i}",
            distinct_query_count=1,
            seed_evidence_count=1,
            directory_title_match=False,
            is_linked_discussion=False,
            freshest_evidence_at=now,
            discovery_channels=("global_message",),
        )
        for i in range(40)
    ]
    assert len(select_sources_for_deep_verification(many)) == 25


def test_build_preliminary_from_evidence_and_directory() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    ev = EvidenceRecord(
        run_id=1,
        source_telegram_id=10,
        source_username="g1",
        source_title="Shop Builders",
        source_type="megagroup",
        telegram_message_id=1,
        published_at=now,
        permalink=None,
        excerpt="hi",
        normalized_hash="h",
        matched_query_ordinals=(1, 2),
        discovery_channels=("global_message",),
        detection_category="irrelevant",
        is_qualified=False,
        hard_exclusion=False,
        hard_exclusion_rule_id=None,
        service_profiles=(),
        rule_set_checksum="x",
    )
    directory = (_source(99, username="dirpeer", title="Ecommerce Hub"),)
    cands = build_preliminary_candidates(
        [ev],
        directory_sources=directory,
        directory_query_texts=("ecommerce",),
        linked_parent_ids={10: 1},
    )
    by_id = {c.telegram_id: c for c in cands}
    assert by_id[10].distinct_query_count == 2
    assert by_id[10].is_linked_discussion is True
    assert by_id[99].directory_title_match is True
    assert by_id[99].seed_evidence_count == 0


def test_merge_duplicates_helper() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    base = dict(
        run_id=1,
        source_telegram_id=1,
        source_username="a",
        source_title="A",
        source_type="group",
        telegram_message_id=9,
        published_at=now,
        permalink=None,
        excerpt="short",
        normalized_hash="h",
        detection_category="irrelevant",
        is_qualified=False,
        hard_exclusion=False,
        hard_exclusion_rule_id=None,
        service_profiles=(),
        rule_set_checksum="c",
    )
    a = EvidenceRecord(
        **base,
        matched_query_ordinals=(1,),
        discovery_channels=("global_message",),
    )
    b = EvidenceRecord(
        **{
            **base,
            "excerpt": "longer excerpt text",
            "published_at": now - timedelta(hours=1),
            "matched_query_ordinals": (2,),
            "discovery_channels": ("directory",),
            "is_qualified": True,
        }
    )
    merged = merge_evidence_duplicates([a, b])
    assert len(merged) == 1
    assert merged[0].matched_query_ordinals == (1, 2)
    assert merged[0].is_qualified is True
    assert merged[0].excerpt == "longer excerpt text"


def test_isolation_module_has_no_pipeline_side_effect_imports() -> None:
    """keyword_search.py must not import Lead/outbox/checkpoint writers."""
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "telegram_lead_discovery"
        / "source_discovery"
        / "keyword_search.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "telegram_lead_discovery.storage.models",
        "telegram_lead_discovery.storage.outbox",
        "telegram_lead_discovery.collector.service",
        "telegram_lead_discovery.processing.pipeline",
    }
    assert forbidden.isdisjoint(imported)
    # Positive: reuses pure detect + score helpers.
    assert "telegram_lead_discovery.detection.engine" in imported
    assert "telegram_lead_discovery.source_discovery.opportunity_score" in imported


def test_real_detect_qualifies_ecommerce_order() -> None:
    excerpt, _hash, detection = qualify_excerpt_text(
        "Нужно разработать интернет-магазин, бюджет 150 000 ₽."
    )
    assert len(excerpt) <= MAX_EVIDENCE_EXCERPT_CODEPOINTS
    assert detection.is_lead is True
    assert "ecommerce" in detection.service_profiles
