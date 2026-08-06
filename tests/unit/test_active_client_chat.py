from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from telegram_lead_discovery.source_discovery.active_chat import (
    ActiveChatAccumulator,
    ActiveChatCounters,
    ActiveChatMessage,
    evaluate_active_client_chat,
    is_countable_client_request,
    source_scoped_author_key,
)
from telegram_lead_discovery.source_discovery.worker_parts import truth_state
from telegram_lead_discovery.source_discovery.worker_parts.acquisition_state import (
    _classify_acquisition_stop,
)

T = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _counters(**overrides) -> ActiveChatCounters:
    values = {
        "activity_message_count": 100,
        "activity_active_day_count": 10,
        "activity_distinct_author_count": 20,
        "client_request_count": 3,
        "client_request_author_count": 3,
        "hard_excluded_count": 0,
        "unknown_author_message_count": 0,
        "latest_client_request_at": T - timedelta(days=7),
    }
    values.update(overrides)
    return ActiveChatCounters(**values)


@pytest.mark.asyncio
async def test_qualified_evidence_never_exceeds_total_cap(monkeypatch) -> None:
    async def total_count(_ctx) -> int:
        return 500

    async def qualified_count(_ctx) -> int:
        return 0

    monkeypatch.setattr(truth_state, "_evidence_count", total_count)
    monkeypatch.setattr(truth_state, "_qualified_evidence_count", qualified_count)
    assert not await truth_state._may_persist_evidence(SimpleNamespace(), is_qualified=True)


@pytest.mark.asyncio
async def test_acquisition_budget_skip_is_not_pool_exhaustion() -> None:
    ctx = SimpleNamespace(
        run=SimpleNamespace(counters_json='{"budget_skipped": 1}'),
        session=None,
    )
    assert await _classify_acquisition_stop(
        ctx,
        pool_size=0,
        acquired_total=10,
    ) == (False, None, "acquisition_budget_cap")


def test_exact_quality_boundaries_and_score() -> None:
    result = evaluate_active_client_chat(_counters(), reference_at=T, stop_reason="quality_reached")
    assert result.truth_status == "quality"
    assert result.score == 95
    assert result.band == "promising"
    assert result.qualification_reasons == ("quality_pass",)
    assert all(result.thresholds.values())


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("activity_message_count", 99, "activity_messages_below_100"),
        ("activity_active_day_count", 9, "activity_days_below_10"),
        ("activity_distinct_author_count", 19, "activity_authors_below_20"),
        ("client_request_count", 2, "client_requests_below_3"),
        ("client_request_author_count", 2, "client_authors_below_3"),
        (
            "latest_client_request_at",
            T - timedelta(days=7, seconds=1),
            "latest_request_older_than_7d",
        ),
    ],
)
def test_each_missing_threshold_is_near_after_complete_scan(field, value, reason) -> None:
    result = evaluate_active_client_chat(
        _counters(**{field: value}), reference_at=T, stop_reason="window_complete"
    )
    assert result.truth_status == "near"
    assert reason in result.qualification_reasons


def test_complete_zero_requests_rejected_but_cap_is_inconclusive() -> None:
    empty = _counters(
        client_request_count=0,
        client_request_author_count=0,
        latest_client_request_at=None,
    )
    rejected = evaluate_active_client_chat(empty, reference_at=T, stop_reason="history_exhausted")
    incomplete = evaluate_active_client_chat(empty, reference_at=T, stop_reason="source_cap")
    assert rejected.truth_status == "rejected"
    assert incomplete.truth_status == "inconclusive"
    assert incomplete.qualification_reasons[-1] == "source_cap_incomplete"


def test_nonterminal_reason_cannot_publish_truth() -> None:
    with pytest.raises(ValueError, match="non_terminal_stop_reason"):
        evaluate_active_client_chat(_counters(), reference_at=T, stop_reason="flood_wait")  # type: ignore[arg-type]


def test_countable_category_requires_human_supported_service_and_no_exclusion() -> None:
    base = {
        "category": "direct_order",
        "service_profiles": ("websites",),
        "hard_exclusion": False,
        "author_kind": "user",
    }
    assert is_countable_client_request(**base)
    assert not is_countable_client_request(**{**base, "category": "potential_need"})
    assert not is_countable_client_request(**{**base, "author_kind": "bot"})
    assert not is_countable_client_request(**{**base, "service_profiles": ("other",)})
    assert not is_countable_client_request(**{**base, "hard_exclusion": True})
    assert not is_countable_client_request(**base, required_service_profiles=("ecommerce",))


def test_profile_requirements_and_exclusions_are_explainable() -> None:
    result = evaluate_active_client_chat(
        _counters(profile_excluded_count=2, matched_service_profiles=("websites",)),
        reference_at=T,
        stop_reason="window_complete",
        required_service_profiles=("ecommerce",),
    )
    assert result.truth_status == "near"
    assert "required_service_profile_miss:ecommerce" in result.qualification_reasons
    assert "profile_additional_exclusion_matches:2" in result.qualification_reasons


def test_source_scoped_author_hash_is_stable_and_unlinkable_across_sources() -> None:
    first = source_scoped_author_key(100, 777)
    assert first == source_scoped_author_key(100, 777)
    assert len(first) == 64 and first == first.lower()
    assert first != source_scoped_author_key(101, 777)


def test_accumulator_counts_activity_demand_authors_and_exact_dedup() -> None:
    accumulator = ActiveChatAccumulator(reference_at=T)
    for index in range(100):
        author = index % 20 + 1
        countable = index < 3
        message = ActiveChatMessage(
            telegram_message_id=index + 1,
            published_at=T - timedelta(days=index % 10),
            normalized_hash=f"hash-{index}",
            author_kind="user",
            author_key=source_scoped_author_key(500, author),
            detection_category="direct_order" if countable else "other",
            service_profiles=("websites",) if countable else (),
            hard_exclusion=False,
        )
        accumulator.consume(message)

    unknown = ActiveChatMessage(
        telegram_message_id=1001,
        published_at=T - timedelta(days=20),
        normalized_hash="same-repost",
        author_kind="unknown",
        author_key=None,
        detection_category="other",
        service_profiles=(),
        hard_exclusion=False,
    )
    accumulator.consume(unknown)
    accumulator.consume(
        ActiveChatMessage(
            telegram_message_id=1002,
            published_at=unknown.published_at,
            normalized_hash=unknown.normalized_hash,
            author_kind="unknown",
            author_key=None,
            detection_category="other",
            service_profiles=(),
            hard_exclusion=False,
        )
    )
    accumulator.consume(unknown)

    counters = accumulator.counters()
    assert counters.activity_message_count == 100
    assert counters.activity_active_day_count == 10
    assert counters.activity_distinct_author_count == 20
    assert counters.client_request_count == 3
    assert counters.client_request_author_count == 3
    assert counters.unknown_author_message_count == 1

    restored = ActiveChatAccumulator.from_cursor(accumulator.to_cursor())
    assert restored.counters() == counters
    assert restored.to_cursor() == accumulator.to_cursor()


def test_score_noise_and_truth_control_band() -> None:
    near = evaluate_active_client_chat(
        _counters(activity_message_count=99, hard_excluded_count=3),
        reference_at=T,
        stop_reason="window_complete",
    )
    assert near.score_components["noise_penalty"] == 15
    assert near.score == 79
    assert near.band == "review"
    incomplete = evaluate_active_client_chat(
        _counters(activity_message_count=99), reference_at=T, stop_reason="run_cap"
    )
    assert incomplete.score == 94
    assert incomplete.band == "weak"


def test_resume_cursor_rejects_changed_reference_instant() -> None:
    restored = ActiveChatAccumulator.from_cursor(ActiveChatAccumulator(reference_at=T).to_cursor())
    with pytest.raises(ValueError, match="active_chat_cursor_reference_mismatch"):
        restored.assert_reference_at(T + timedelta(seconds=1))
