"""Unit tests — Wave 03 keyword novelty, eligibility, profile semantics (SRC-037..045)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.ports import SearchMessageHitDTO, SourceSnapshot
from telegram_lead_discovery.detection.engine import DetectionResult
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    match_additional_exclusion,
    schedule_balanced_query_kinds,
    select_deep_verification_queries,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    AnnotatedSearchHit,
    EvidenceRecord,
    PresentationCooldownIndex,
    acquire_with_replacement,
    aggregate_search_hits,
    apply_neutral_noise_sample,
    build_opportunity_from_evidence,
    linked_discussion_opportunity,
    merge_funnel_counters,
)
from telegram_lead_discovery.source_discovery.opportunity_score import (
    apply_opportunity_eligibility,
    band_for_score,
    score_opportunity,
)


def _source(
    telegram_id: int,
    *,
    username: str = "chat",
    title: str = "Chat",
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
    username: str | None = None,
) -> SearchMessageHitDTO:
    uname = username or f"u{telegram_id}"
    return SearchMessageHitDTO(
        schema_version=1,
        source=_source(telegram_id, username=uname, title=uname),
        telegram_message_id=message_id,
        published_at=published_at,
        permalink=f"https://t.me/{uname}/{message_id}",
        excerpt=excerpt,
    )


def _fake_detect(
    category: str = "direct_order",
    *,
    is_lead: bool = True,
    hard: bool = False,
    services: tuple[str, ...] = ("ecommerce",),
) -> DetectionResult:
    return DetectionResult(
        category=category,
        is_lead=is_lead,
        hard_exclusion=hard,
        hard_exclusion_rule_id="EXCL" if hard else None,
        matched_rules=(),
        service_profiles=services if is_lead else (),
        timed_out_rule_ids=(),
        signals={},
        explanation_codes=(),
        duration_ms=1,
        rule_set_checksum="chk",
    )


def test_replacement_fills_after_first_30_suppressed() -> None:
    """100 provider rows, first 30 suppressed → replacements fill quota."""
    suppressed = frozenset(range(1, 31))
    pages = [
        tuple(range(1, 51)),
        tuple(range(51, 101)),
    ]
    result = acquire_with_replacement(
        pages,
        is_suppressed=lambda tid: tid in suppressed,
        target_quota=50,
    )
    assert result.acquired_total == 100
    assert result.suppressed_total == 30
    assert result.qualified_candidate_ids[:50] == list(range(31, 81))
    assert result.replacement_fetches_total >= 1
    assert result.pool_exhausted is False
    assert len(result.qualified_candidate_ids) >= 50


def test_pool_exhaustion_visible_not_masked_as_success() -> None:
    suppressed = frozenset(range(1, 21))
    pages = [tuple(range(1, 11)), tuple(range(11, 21))]
    result = acquire_with_replacement(
        pages,
        is_suppressed=lambda tid: tid in suppressed,
        target_quota=25,
    )
    assert result.pool_exhausted is True
    assert result.pool_exhausted_reason == "no_unseen_after_suppress"
    assert len(result.qualified_candidate_ids) == 0


def test_same_source_post_and_directory_one_opportunity() -> None:
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    hit_post = _hit(
        telegram_id=7001,
        message_id=1,
        excerpt="нужен интернет-магазин",
        published_at=now - timedelta(days=1),
        username="shop_peer",
    )
    hit_dir = _hit(
        telegram_id=7001,
        message_id=2,
        excerpt="нужен telegram бот",
        published_at=now - timedelta(hours=3),
        username="Shop_Peer",
    )
    result = aggregate_search_hits(
        [
            AnnotatedSearchHit(hit_post, 1, "public_posts"),
            AnnotatedSearchHit(hit_dir, 2, "directory"),
        ],
        run_id=1,
        scored_at=now,
        detect_fn=lambda _t: _fake_detect(),
    )
    assert len(result.opportunities) == 1
    assert result.opportunities[0].source_telegram_id == 7001
    assert set(result.opportunities[0].discovery_channels) >= {
        "public_posts",
        "directory",
    }


def test_service_specific_deep_verification_query_selected() -> None:
    posts = (
        "нужен разработчик сайта",
        "ищу разработчика сайта",
        "кто сделает сайт",
        "посоветуйте разработчика",
        "нужно разработать сайт",
        "нужен интернет-магазин",
        "разработать telegram бота",
        "нужен парсер",
    )
    selected = select_deep_verification_queries(
        posts,
        required_service_profiles=("ecommerce",),
        limit=5,
    )
    assert len(selected) <= 5
    assert any("магазин" in q or "ecommerce" in q for q in selected)
    # Must not be naive global prefix [:5] when service profile is set.
    assert selected != posts[:5]


def test_additional_exclusion_blocks_right_candidate_only() -> None:
    assert match_additional_exclusion(
        "предлагаю услуги разработки сайтов",
        ("предлагаю услуги", "курс"),
    ) == "profile_additional_exclusion:предлагаю услуги"
    assert (
        match_additional_exclusion(
            "нужен интернет-магазин под ключ",
            ("предлагаю услуги", "курс"),
        )
        is None
    )


def test_neutral_noise_sample_affects_noisy_signal() -> None:
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    source = _source(77)
    qualified = [
        EvidenceRecord(
            run_id=1,
            source_telegram_id=77,
            source_username="devchat",
            source_title="Dev Chat",
            source_type="megagroup",
            telegram_message_id=i,
            published_at=now - timedelta(days=i),
            permalink=None,
            excerpt="нужен интернет-магазин",
            normalized_hash=f"h{i}",
            matched_query_ordinals=(1,),
            discovery_channels=("source_verification",),
            detection_category="direct_order",
            is_qualified=True,
            hard_exclusion=False,
            hard_exclusion_rule_id=None,
            service_profiles=("ecommerce",),
            rule_set_checksum="x",
        )
        for i in range(1, 4)
    ]
    base = build_opportunity_from_evidence(
        run_id=1,
        source=source,
        evidence=qualified,
        scored_at=now,
    )
    noisy = apply_neutral_noise_sample(
        base,
        neutral_excluded_count=6,
        neutral_sample_count=6,
    )
    assert noisy.excluded_count == base.excluded_count + 6
    assert noisy.score_components["noise_penalty"] > base.score_components["noise_penalty"]
    assert noisy.score <= base.score
    assert "neutral_noise_sample" in noisy.score_components.get("reason_codes", []) or (
        "neutral_noise_sample" in (noisy.score_components.get("eligibility_reasons") or [])
    )


def test_directory_only_cannot_be_review_or_promising() -> None:
    scored = score_opportunity(
        qualified_count=5,
        excluded_count=0,
        ecommerce_qualified_count=3,
        last_qualified_at=datetime(2026, 7, 26, tzinfo=UTC),
        scored_at=datetime(2026, 7, 27, tzinfo=UTC),
        active_week_count=4,
    )
    assert scored.band == "promising"
    gated = apply_opportunity_eligibility(
        score_result=scored,
        discovery_channels=("directory",),
        has_message_evidence=False,
        has_verification_evidence=False,
        is_linked_discussion=False,
    )
    assert gated.band == "weak"
    assert gated.score <= 34
    assert "directory_only_no_evidence" in gated.reason_codes


def test_linked_without_evidence_needs_verification_not_forever_score0_trap() -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    discussion = _source(200, username="channelchat", title="Channel Chat")
    opp = linked_discussion_opportunity(
        run_id=3,
        parent_telegram_id=100,
        discussion=discussion,
        scored_at=now,
    )
    assert opp.band == "weak"
    reasons = opp.score_components.get("eligibility_reasons") or opp.score_components.get(
        "reason_codes"
    )
    assert reasons is not None
    assert "needs_verification" in reasons
    # Must not look like a scored review/promising candidate.
    assert opp.band not in ("review", "promising")


def test_required_service_profiles_affect_eligibility() -> None:
    scored = score_opportunity(
        qualified_count=4,
        excluded_count=0,
        ecommerce_qualified_count=0,
        last_qualified_at=datetime(2026, 7, 26, tzinfo=UTC),
        scored_at=datetime(2026, 7, 27, tzinfo=UTC),
        active_week_count=3,
    )
    gated = apply_opportunity_eligibility(
        score_result=scored,
        discovery_channels=("global_message", "source_verification"),
        has_message_evidence=True,
        has_verification_evidence=True,
        is_linked_discussion=False,
        matched_service_profiles=("bot_dev",),
        required_service_profiles=("ecommerce",),
    )
    assert "required_service_profile_miss:ecommerce" in gated.reason_codes
    assert gated.band == "weak" or gated.score < scored.total


def test_query_scheduling_balances_post_directory_service() -> None:
    kinds = schedule_balanced_query_kinds(
        post_count=3,
        directory_count=2,
        include_public_posts=True,
    )
    assert kinds.count("global_message") == 3
    assert kinds.count("directory") == 2
    assert kinds.count("public_posts") == 3
    # Not all globals first: directory appears before the last global.
    first_dir = kinds.index("directory")
    last_global = max(i for i, k in enumerate(kinds) if k == "global_message")
    assert first_dir < last_global


def test_presented_suppress_is_durable_not_24h_cooldown() -> None:
    """D-069: membership in presented index suppresses permanently (alias API)."""
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    cooldown = PresentationCooldownIndex.from_entries(
        [
            (42, now - timedelta(hours=2)),
            (99, now - timedelta(hours=30)),
        ]
    )
    assert cooldown.is_cooled_down(42, now=now) is True
    assert cooldown.is_cooled_down(99, now=now) is True
    assert cooldown.is_cooled_down(7, now=now) is False


def test_funnel_presented_suppressed_aliases_cooldown() -> None:
    counters = merge_funnel_counters({}, presented_suppressed=4)
    assert counters["presented_suppressed"] == 4
    assert counters["cooldown_suppressed"] == 4
    counters2 = merge_funnel_counters({}, cooldown_suppressed=3)
    assert counters2["presented_suppressed"] == 3
    assert counters2["cooldown_suppressed"] == 3


def test_seed_directory_covers_service_families_and_client_communities() -> None:
    from telegram_lead_discovery.source_discovery.keyword_profiles import (
        SEED_DIRECTORY_QUERIES,
        SEED_DIRECTORY_REPLACEMENT_QUERIES,
        SEED_PROFILE_VERSION,
        build_seed_normalized_profile,
    )

    assert SEED_PROFILE_VERSION >= 2
    profile = build_seed_normalized_profile()
    joined_posts = " ".join(profile.post_queries)
    for token in ("сайт", "бот", "интеграц", "парсер", "магазин"):
        assert token in joined_posts
    joined_dirs = " ".join(SEED_DIRECTORY_QUERIES) + " " + " ".join(
        SEED_DIRECTORY_REPLACEMENT_QUERIES
    )
    assert "предпринимател" in joined_dirs or "заказчик" in joined_dirs
    assert "селлер" not in " ".join(SEED_DIRECTORY_QUERIES)
    assert "маркетплейс" not in " ".join(SEED_DIRECTORY_QUERIES)
    assert len(SEED_DIRECTORY_REPLACEMENT_QUERIES) >= 10
    assert len(set(SEED_DIRECTORY_QUERIES) & set(SEED_DIRECTORY_REPLACEMENT_QUERIES)) == 0


def test_five_run_novelty_fixture_ge_80_percent_and_dismissed_zero() -> None:
    """Deterministic novelty ≥80% with sufficient pool; dismissed recurrence = 0."""
    dismissed_ids = frozenset({42})
    presented_history: list[frozenset[int]] = []
    novel_ratios: list[float] = []

    pool = list(range(100, 220))  # sufficient replacement pool
    cursor = 0
    for _run_idx in range(5):
        page = pool[cursor : cursor + 40]
        cursor += 20
        # Inject dismissed peer into every run's provider page.
        provider_ids = [42, *page]
        prior = (
            frozenset().union(*presented_history) if presented_history else frozenset()
        )
        acquired = acquire_with_replacement(
            [tuple(provider_ids)],
            is_suppressed=lambda tid, _d=dismissed_ids, _h=prior: tid in _d or tid in _h,
            target_quota=20,
        )
        presented = frozenset(acquired.qualified_candidate_ids[:20])
        assert 42 not in presented
        novel = presented - prior
        ratio = len(novel) / max(1, len(presented))
        novel_ratios.append(ratio)
        counters = merge_funnel_counters(
            {},
            acquired_total=acquired.acquired_total,
            suppressed_total=acquired.suppressed_total,
            presented_total=len(presented),
            novel_presented_total=len(novel),
        )
        assert counters["novelty_ratio_bp"] >= 0
        presented_history.append(presented)

    # After first run, subsequent novelty should keep overall gate ≥80% median.
    after_first = novel_ratios[1:]
    assert all(r >= 0.80 for r in after_first)
    dismissed_recurrence = sum(1 for batch in presented_history if 42 in batch)
    assert dismissed_recurrence == 0


def test_funnel_stages_counters_merge() -> None:
    counters = merge_funnel_counters(
        {"registry_suppressed": 2},
        acquired_total=100,
        canonicalized_total=90,
        dismissed_suppressed=5,
        cooldown_suppressed=3,
        qualified_total=40,
        presented_total=25,
        novel_presented_total=20,
        replacement_fetches_total=2,
        pool_exhausted=True,
        pool_exhausted_reason="no_unseen_after_suppress",
    )
    assert counters["acquired_total"] == 100
    assert counters["canonicalized_total"] == 90
    assert counters["registry_suppressed"] == 2
    assert counters["dismissed_suppressed"] == 5
    assert counters["cooldown_suppressed"] == 3
    assert counters["qualified_total"] == 40
    assert counters["presented_total"] == 25
    assert counters["novel_presented_total"] == 20
    assert counters["novelty_ratio_bp"] == 8000  # 20/25 * 10000
    assert counters["pool_exhausted"] == 1
    assert counters["pool_exhausted_reason_code"] >= 0


def test_band_aliases_remain_promising_review_weak() -> None:
    assert band_for_score(60) == "promising"
    assert band_for_score(35) == "review"
    assert band_for_score(10) == "weak"
