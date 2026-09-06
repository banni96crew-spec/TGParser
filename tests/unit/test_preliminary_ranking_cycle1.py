from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.collector.fake import make_source
from telegram_lead_discovery.source_discovery.evidence import EvidenceRecord
from telegram_lead_discovery.source_discovery.identity import (
    RegistrySourceEntry,
    SourceRegistryIndex,
)
from telegram_lead_discovery.source_discovery.quality_truth import pick_next_fair_source
from telegram_lead_discovery.source_discovery.ranking import (
    DIVERSITY_RESERVATIONS,
    PreliminarySourceCandidate,
    build_preliminary_candidates,
    diversity_reservations_for_profile,
    preliminary_rank_key,
    select_preliminary_candidates,
)
from telegram_lead_discovery.source_discovery.worker_parts.verification_phase import (
    _candidate_pool_item,
    _should_rebuild_acquisition_pool,
)

NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _candidate(
    telegram_id: int,
    *,
    strong: int = 0,
    qualified: int = 0,
    queries: int = 0,
    potential: int = 0,
    raw: int = 0,
    search: bool = False,
    directory: bool = False,
    linked: bool = False,
    operator_seed: bool = False,
    title_match: bool = False,
) -> PreliminarySourceCandidate:
    return PreliminarySourceCandidate(
        telegram_id=telegram_id,
        source_type="megagroup",
        title=f"Source {telegram_id}",
        username=f"source_{telegram_id}",
        raw_evidence_count=raw,
        qualified_evidence_count=qualified,
        qualified_distinct_query_count=queries,
        strong_buyer_intent_count=strong,
        potential_need_count=potential,
        freshest_seed_evidence_at=NOW - timedelta(minutes=telegram_id),
        directory_title_match=title_match,
        is_search_candidate=search,
        is_directory_candidate=directory,
        is_operator_seed_candidate=operator_seed,
        is_linked_discussion=linked,
    )


def _evidence(
    telegram_id: int,
    message_id: int,
    *,
    category: str = "irrelevant",
    qualified: bool = False,
    channel: str = "global_message",
    ordinals: tuple[int, ...] = (1,),
    hard_exclusion: bool = False,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=1,
        source_telegram_id=telegram_id,
        source_username=f"source_{telegram_id}",
        source_title=f"Source {telegram_id}",
        source_type="megagroup",
        telegram_message_id=message_id,
        published_at=NOW - timedelta(minutes=message_id),
        permalink=None,
        excerpt="evidence",
        normalized_hash=f"hash-{telegram_id}-{message_id}",
        matched_query_ordinals=ordinals,
        discovery_channels=(channel,),  # type: ignore[arg-type]
        detection_category=category,
        is_qualified=qualified,
        hard_exclusion=hard_exclusion,
        hard_exclusion_rule_id="x" if hard_exclusion else None,
        service_profiles=("websites",) if qualified else (),
        rule_set_checksum="checksum",
    )


def test_01_buyer_beats_raw() -> None:
    noisy = _candidate(1, raw=30, search=True)
    buyer = _candidate(2, strong=3, qualified=3, queries=3, raw=4, search=True)
    assert [item.telegram_id for item in select_preliminary_candidates([noisy, buyer])] == [2, 1]


def test_02_raw_is_only_a_weak_tie_breaker() -> None:
    better = _candidate(1, strong=1, raw=1, search=True)
    raw_heavy = _candidate(2, raw=1000, search=True)
    assert preliminary_rank_key(better) < preliminary_rank_key(raw_heavy)


def test_03_full_diversity_allocation_and_global_fill() -> None:
    candidates = (
        [_candidate(i, linked=True) for i in range(1, 6)]
        + [_candidate(i, directory=True) for i in range(10, 15)]
        + [_candidate(20)]
        + [_candidate(i, strong=10, search=True) for i in range(30, 60)]
    )
    selected = select_preliminary_candidates(candidates)
    reserved = [item for item in selected if item.selection_phase == "diversity_reserved"]
    assert len(selected) == 25
    assert DIVERSITY_RESERVATIONS["DIRECTORY"] == 0
    assert sum(item.selected_lane == "LINKED_DISCUSSION" for item in reserved) == 3
    assert sum(item.selected_lane == "DIRECTORY" for item in reserved) == 0
    assert sum(item.selected_lane == "EXPLORATION" for item in reserved) == 1
    assert sum(item.selection_phase == "global_fill" for item in selected) == 21


def test_04_empty_lane_capacity_moves_to_global_fill() -> None:
    candidates = [_candidate(i, search=True) for i in range(30)]
    assert len(select_preliminary_candidates(candidates)) == 25


def test_05_overlap_ownership_prefers_operator_seed_then_linked() -> None:
    item = select_preliminary_candidates(
        [_candidate(1, search=True, directory=True, linked=True, operator_seed=True)]
    )[0]
    assert item.selected_lane == "OPERATOR_SEED"


def test_05b_overlap_without_seed_prefers_linked_once() -> None:
    item = select_preliminary_candidates(
        [_candidate(1, search=True, directory=True, linked=True)]
    )[0]
    assert item.selected_lane == "LINKED_DISCUSSION"


def test_06_search_directory_ownership_prefers_directory() -> None:
    item = select_preliminary_candidates([_candidate(1, search=True, directory=True)])[0]
    assert item.selected_lane == "DIRECTORY"


def test_07_search_only_owns_search_lane_without_reservation() -> None:
    item = select_preliminary_candidates([_candidate(1, search=True)])[0]
    assert item.selected_lane == "SEARCH"
    assert item.selection_phase == "global_fill"


def test_08_directory_has_reserved_representation_when_directory_queries_exist() -> None:
    candidates = [_candidate(i, strong=5, search=True) for i in range(1, 31)]
    candidates += [_candidate(100 + i, directory=True) for i in range(3)]
    selected = select_preliminary_candidates(
        candidates,
        diversity_reservations=diversity_reservations_for_profile(directory_query_count=1),
    )
    assert sum(item.selected_lane == "DIRECTORY" for item in selected) == 3


def test_09_linked_has_reserved_representation_over_25_search_candidates() -> None:
    candidates = [_candidate(i, strong=5, search=True) for i in range(1, 31)]
    candidates += [_candidate(100 + i, linked=True) for i in range(3)]
    selected = select_preliminary_candidates(candidates)
    assert sum(item.selected_lane == "LINKED_DISCUSSION" for item in selected) == 3


def test_10_selector_rejects_duplicate_identity() -> None:
    with pytest.raises(ValueError, match="unique_telegram_ids"):
        select_preliminary_candidates([_candidate(1), _candidate(1, search=True)])


def test_11_selection_is_deterministic() -> None:
    candidates = [_candidate(i, search=i % 2 == 0, directory=i % 5 == 0) for i in range(40)]
    baseline = select_preliminary_candidates(candidates)
    expected = [
        (
            x.telegram_id,
            x.selected_lane,
            x.selection_phase,
            x.selection_reason,
            x.preliminary_position,
        )
        for x in baseline
    ]
    for _ in range(5):
        actual = select_preliminary_candidates(list(reversed(candidates)))
        assert [
            (
                x.telegram_id,
                x.selected_lane,
                x.selection_phase,
                x.selection_reason,
                x.preliminary_position,
            )
            for x in actual
        ] == expected


def test_12_builder_applies_suppression_before_selector() -> None:
    registry = SourceRegistryIndex.from_entries(
        [RegistrySourceEntry(source_id=1, telegram_id=1, username_normalized="source_1")]
    )
    candidates = build_preliminary_candidates(
        [_evidence(1, 1), _evidence(2, 1)], registry=registry
    )
    assert [item.telegram_id for item in candidates] == [2]


def test_13_capacity_never_exceeds_25() -> None:
    assert len(select_preliminary_candidates([_candidate(i) for i in range(100)])) == 25


def test_14_replacement_reenters_full_builder_and_selector() -> None:
    initial = make_source(telegram_id=1, username="source_1", source_type="megagroup")
    replacement = make_source(telegram_id=2, username="source_2", source_type="megagroup")
    before = build_preliminary_candidates([], directory_sources=[initial])
    after = build_preliminary_candidates([], directory_sources=[initial, replacement])
    assert [item.telegram_id for item in select_preliminary_candidates(before)] == [1]
    assert {item.telegram_id for item in select_preliminary_candidates(after)} == {1, 2}


def test_15_replacement_without_evidence_has_no_buyer_advantage() -> None:
    replacement = make_source(telegram_id=2, username="source_2", source_type="megagroup")
    item = build_preliminary_candidates([], directory_sources=[replacement])[0]
    assert (
        item.raw_evidence_count,
        item.qualified_evidence_count,
        item.strong_buyer_intent_count,
    ) == (0, 0, 0)


def test_16_builder_metrics_use_seed_evidence_only() -> None:
    evidence = [
        _evidence(1, 1, category="direct_order", qualified=True, ordinals=(1, 2)),
        _evidence(1, 2, category="potential_need", qualified=True, ordinals=(2, 3)),
        _evidence(1, 3, hard_exclusion=True),
        _evidence(1, 4, category="direct_order", qualified=True, channel="source_verification"),
    ]
    item = build_preliminary_candidates(evidence)[0]
    assert item.raw_evidence_count == 3
    assert item.qualified_evidence_count == 2
    assert item.qualified_distinct_query_count == 3
    assert item.strong_buyer_intent_count == 1
    assert item.potential_need_count == 1
    assert item.hard_excluded_count == 1


def test_17_provenance_is_explicit_not_inferred_from_title_match() -> None:
    snap = make_source(
        telegram_id=1,
        username="source_1",
        source_type="megagroup",
        title="Website directory match",
    )
    item = build_preliminary_candidates(
        [],
        directory_sources=[snap],
        directory_query_texts=["website"],
        directory_candidate_ids=set(),
        linked_parent_ids={1: 99},
    )[0]
    assert item.directory_title_match is True
    assert item.is_directory_candidate is False
    assert item.is_linked_discussion is True


def test_18_pool_can_rebuild_only_before_verification_starts() -> None:
    pool = [{"telegram_id": 1}]
    assert _should_rebuild_acquisition_pool(pool, verification_started=False) is True
    assert _should_rebuild_acquisition_pool(pool, verification_started=True) is False


def test_19_frozen_pool_metadata_and_order_survive_json_resume() -> None:
    selected = select_preliminary_candidates(
        [_candidate(1, linked=True), _candidate(2, strong=5, search=True)]
    )
    pool = [_candidate_pool_item(item) for item in selected]
    restored = json.loads(json.dumps({"acquisition_pool": pool}))["acquisition_pool"]
    assert restored == pool
    assert _should_rebuild_acquisition_pool(restored, verification_started=True) is False


def test_20_legacy_pool_cursor_remains_readable_and_frozen() -> None:
    legacy = json.loads('{"acquisition_pool":[{"telegram_id":7,"source_type":"megagroup"}]}')
    assert _should_rebuild_acquisition_pool(
        legacy["acquisition_pool"], verification_started=True
    ) is False


def test_21_reserved_admission_does_not_override_final_buyer_order() -> None:
    selected = select_preliminary_candidates(
        [
            _candidate(1, linked=True),
            _candidate(2, directory=True),
            _candidate(3, strong=5, search=True),
        ]
    )
    assert [item.telegram_id for item in selected] == [3, 1, 2]
    by_id = {item.telegram_id: item for item in selected}
    assert by_id[1].selection_phase == "diversity_reserved"
    assert by_id[2].selection_phase == "global_fill"
    assert by_id[3].selection_phase == "global_fill"


def test_selector_persistence_scheduler_coupling() -> None:
    selected = select_preliminary_candidates(
        [
            _candidate(1, linked=True),
            _candidate(2, directory=True),
            _candidate(3, strong=5, search=True),
        ]
    )
    persisted = json.loads(json.dumps([_candidate_pool_item(item) for item in selected]))
    assert pick_next_fair_source(
        pool_telegram_ids=[int(item["telegram_id"]) for item in persisted],
        scanned_by_source={},
        finished_sources=set(),
        source_cap=1500,
    ) == 3


def test_integrated_business_fixture_over_25_candidates() -> None:
    buyer_search = [
        _candidate(i, strong=6, qualified=6, queries=3, raw=6, search=True)
        for i in range(1, 20)
    ]
    noisy_search = [_candidate(i, raw=100, search=True) for i in range(20, 36)]
    alternatives = [
        _candidate(101, directory=True),
        _candidate(102, directory=True, search=True),
        _candidate(103, linked=True),
        _candidate(104, linked=True, search=True),
        _candidate(105, linked=True, directory=True),
        _candidate(106),
    ]
    selected = select_preliminary_candidates(buyer_search + noisy_search + alternatives)
    ids = {item.telegram_id for item in selected}
    assert len(selected) == 25
    assert {item.telegram_id for item in buyer_search}.issubset(ids)
    assert {103, 104, 105, 106}.issubset(ids)
    assert selected[0].strong_buyer_intent_count == 6
    assert selected[-1].strong_buyer_intent_count == 0
    assert [item.preliminary_position for item in selected] == list(range(1, 26))


def test_global_rank_key_ignores_directory_bit() -> None:
    directory = _candidate(1, strong=1, search=True, directory=True)
    search_only = _candidate(1, strong=1, search=True, directory=False)
    assert preliminary_rank_key(directory) == preliminary_rank_key(search_only)


def test_operator_seed_reservation_admits_seeds_over_search_fill() -> None:
    candidates = [_candidate(i, strong=5, search=True) for i in range(1, 31)]
    seeds = [_candidate(200 + i, operator_seed=True) for i in range(2)]
    selected = select_preliminary_candidates(
        candidates + seeds,
        diversity_reservations=diversity_reservations_for_profile(operator_seed_count=2),
    )
    assert {200, 201}.issubset({item.telegram_id for item in selected})
    assert sum(item.selected_lane == "OPERATOR_SEED" for item in selected) == 2
