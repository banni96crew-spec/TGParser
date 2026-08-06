"""Focused unit tests for working-client-search quality truth / DET provenance (D-068)."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.detection.engine import detect, seed_catalog_detect
from telegram_lead_discovery.detection.seed import ACTIVE_SEED_RULES, catalog_checksum
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.source_discovery.quality_truth import (
    ClientRequestIdentity,
    classify_truth_status,
    distinct_client_request_count,
    evaluate_run_gate,
    is_client_request,
    is_within_quality_window,
    pick_next_fair_source,
)


def _load_live_fixture():
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "calibration"
        / "live_run13_c01_c20.py"
    )
    spec = importlib.util.spec_from_file_location("live_run13_c01_c20", fixture_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_legacy_request_only_truth_cannot_claim_active_chat_quality() -> None:
    assert (
        classify_truth_status(
            distinct_qualified_in_window=6,
            window_complete=True,
            hit_source_cap=False,
            hit_run_cap=False,
        )
        == "inconclusive"
    )
    assert (
        classify_truth_status(
            distinct_qualified_in_window=7,
            window_complete=False,
            hit_source_cap=False,
            hit_run_cap=False,
        )
        == "inconclusive"
    )


def test_thirty_day_demand_boundary() -> None:
    now = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    inside = now - timedelta(days=30)
    outside = now - timedelta(days=30, seconds=1)
    assert is_within_quality_window(inside, now=now) is True
    assert is_within_quality_window(outside, now=now) is False


def test_source_cap_and_run_cap_are_inconclusive_not_rejected() -> None:
    assert (
        classify_truth_status(
            distinct_qualified_in_window=0,
            window_complete=False,
            hit_source_cap=True,
            hit_run_cap=False,
        )
        == "inconclusive"
    )
    assert (
        classify_truth_status(
            distinct_qualified_in_window=0,
            window_complete=False,
            hit_source_cap=False,
            hit_run_cap=True,
        )
        == "inconclusive"
    )
    assert (
        classify_truth_status(
            distinct_qualified_in_window=3,
            window_complete=False,
            hit_source_cap=False,
            hit_run_cap=True,
        )
        == "inconclusive"
    )
    assert (
        classify_truth_status(
            distinct_qualified_in_window=0,
            window_complete=True,
            hit_source_cap=False,
            hit_run_cap=False,
        )
        == "rejected"
    )


def test_gate_one_quality_passes() -> None:
    fail = evaluate_run_gate(
        truth_statuses=("quality",) * 4 + ("near",),
        globally_distinct_client_requests=28,
    )
    assert fail.gate_status == "pass"
    ok = evaluate_run_gate(
        truth_statuses=("quality",) * 5,
        globally_distinct_client_requests=35,
    )
    assert ok.gate_status == "pass"
    assert ok.quality_sources == 5


def test_gate_run_cap_before_pool_exhausted_is_inconclusive() -> None:
    result = evaluate_run_gate(
        truth_statuses=("near",) * 3 + ("inconclusive",) * 5 + ("rejected",) * 2,
        globally_distinct_client_requests=15,
        hit_run_cap=True,
        pool_exhausted=False,
    )
    assert result.gate_status == "inconclusive"


def test_gate_pool_exhausted_below_target_is_fail() -> None:
    result = evaluate_run_gate(
        truth_statuses=("rejected",) * 10 + ("near",) * 2,
        globally_distinct_client_requests=10,
        hit_run_cap=False,
        pool_exhausted=True,
    )
    assert result.gate_status == "fail"


def test_pick_next_fair_source_probes_later_before_early_monopoly() -> None:
    pool = [101, 102, 103, 104]
    scanned = {101: 200, 102: 0, 103: 0, 104: 0}
    next_tid = pick_next_fair_source(
        pool_telegram_ids=pool,
        scanned_by_source=scanned,
        finished_sources=set(),
    )
    assert next_tid == 102
    scanned[102] = 100
    assert (
        pick_next_fair_source(
            pool_telegram_ids=pool,
            scanned_by_source=scanned,
            finished_sources=set(),
        )
        == 103
    )
    # Early weak source at 1499 still waits while others are lower.
    scanned = {101: 1499, 102: 100, 103: 100, 104: 50}
    assert (
        pick_next_fair_source(
            pool_telegram_ids=pool,
            scanned_by_source=scanned,
            finished_sources=set(),
        )
        == 104
    )


def test_exact_repost_counts_once_globally() -> None:
    same_hash = "abc123"
    count = distinct_client_request_count(
        [
            ClientRequestIdentity(1, 10, same_hash),
            ClientRequestIdentity(2, 99, same_hash),  # exact repost C01/C05
            ClientRequestIdentity(3, 11, "other"),
        ]
    )
    assert count == 2


def test_live_c01_c20_provenance_and_ground_truth() -> None:
    """AT-DET-017 provenance honesty: C* live, T* DET-A golden only."""
    mod = _load_live_fixture()
    manifest = mod.CORPUS_MANIFEST
    assert manifest["schema_version"] == "det-live-c01-c20.v2"
    assert manifest["live_run_id"] == 13
    assert len(manifest["live_sample_ids"]) == 20
    assert set(manifest["live_client_ids"]) == {"C01", "C05", "C06"}
    assert len(manifest["live_negative_ids"]) == 17
    assert manifest["provenance_live"] == "operator_run_13_sanitized_excerpt"
    assert manifest["provenance_golden"] == "det_a_golden"
    assert "population" in manifest["sample_size_note"].lower()

    assert manifest["evidence_id_by_sample"]["C01"] == 59
    assert manifest["evidence_id_by_sample"]["C07"] == 24
    assert manifest["evidence_id_by_sample"]["C08"] == 26
    assert manifest["evidence_id_by_sample"]["C20"] == 66

    live = mod.iter_live_samples()
    assert len(live) == 20
    assert all(p == mod.PROVENANCE_LIVE for *_, p in live)
    positives = [sid for sid, _, is_client, _ in live if is_client]
    negatives = [sid for sid, _, is_client, _ in live if not is_client]
    assert positives == ["C01", "C05", "C06"]
    assert len(negatives) == 17

    c01 = mod.LIVE_TEXTS["C01"]
    c05 = mod.LIVE_TEXTS["C05"]
    assert c01 == c05
    assert normalize_message_text(c01) == normalize_message_text(c05)
    assert "ИИ-агент" in c01

    assert "выгружать товар" in mod.LIVE_TEXTS["C07"]
    assert "SERVICE TG" in mod.LIVE_TEXTS["C08"]
    assert "внедрение ИИ" not in mod.LIVE_TEXTS["C07"]

    assert "Даниил" not in mod.LIVE_TEXTS["C02"]
    assert "[скрыто]" in mod.LIVE_TEXTS["C02"]
    assert "Андрей" not in mod.LIVE_TEXTS["C20"]

    golden = mod.iter_golden_samples()
    assert len(golden) == 5
    assert all(p == mod.PROVENANCE_GOLDEN for *_, p in golden)
    assert all(sid.startswith("T") for sid, *_ in golden)

    jsonl_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "calibration"
        / "live_run13_c01_c20.jsonl"
    )
    assert jsonl_path.is_file()
    rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith('{"_manifest"')
    ]
    assert len(rows) == 25
    for row in rows:
        if row["id"].startswith("C"):
            assert row["provenance"] == "operator_run_13_sanitized_excerpt"
            assert row["evidence_id"] == manifest["evidence_id_by_sample"][row["id"]]
        else:
            assert row["id"].startswith("T")
            assert row["provenance"] == "det_a_golden"
            assert "evidence_id" not in row


def test_det_calibration_live_and_combined_metrics() -> None:
    """AT-DET-017 / NFR-QLT-007: report live-only + combined; gate on combined ≥80/80."""
    mod = _load_live_fixture()
    checksum = catalog_checksum(ACTIVE_SEED_RULES)

    def _matrix(samples: list[tuple[str, str, bool]]) -> tuple[int, int, int, int, float, float]:
        tp = fp = fn = tn = 0
        for _id, text, is_client in samples:
            result = detect(text, rules=ACTIVE_SEED_RULES, rule_set_checksum=checksum)
            predicted = is_client_request(
                category=result.category,
                service_profiles=result.service_profiles,
                hard_exclusion=result.hard_exclusion,
            )
            if is_client and predicted:
                tp += 1
            elif not is_client and predicted:
                fp += 1
            elif is_client and not predicted:
                fn += 1
            else:
                tn += 1
            if _id == "C06":
                assert "ecommerce" in result.service_profiles
                assert result.hard_exclusion is False
            if _id in {"C02", "C03", "C04"}:
                assert result.hard_exclusion is True or result.category == "advertising"
            if _id in {"C01", "C05"}:
                assert predicted is True
                assert "integrations_api" in result.service_profiles
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        return tp, fp, fn, tn, precision, recall

    live_only = [(sid, text, is_client) for sid, text, is_client, _ in mod.iter_live_samples()]
    live_tp, live_fp, live_fn, live_tn, live_p, live_r = _matrix(live_only)
    assert live_tp + live_fn == 3
    assert live_tn + live_fp == 17
    print(
        f"live_only_confusion tp={live_tp} fp={live_fp} fn={live_fn} tn={live_tn} "
        f"precision={live_p:.3f} recall={live_r:.3f}"
    )

    combined = mod.iter_labeled_samples()
    tp, fp, fn, tn, precision, recall = _matrix(combined)
    print(
        f"combined_confusion tp={tp} fp={fp} fn={fn} tn={tn} "
        f"precision={precision:.3f} recall={recall:.3f}"
    )
    assert precision >= 0.80, f"combined precision={precision:.3f} tp={tp} fp={fp}"
    assert recall >= 0.80, f"combined recall={recall:.3f} tp={tp} fn={fn}"
    assert seed_catalog_detect("Сделаю сайт под ключ").hard_exclusion is True
    assert len([x for x in live_only if x[2]]) == 3


def test_run14_precision_regression_and_separate_metrics() -> None:
    """AT-DET-018: run14 FPs excluded; KEEP retained; C/T still ≥80/80; honest provenance."""
    r14_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "calibration"
        / "live_run14_precision_regression.py"
    )
    spec = importlib.util.spec_from_file_location("live_run14_precision_regression", r14_path)
    assert spec is not None and spec.loader is not None
    r14 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r14)

    checksum = catalog_checksum(ACTIVE_SEED_RULES)
    assert r14.PROVENANCE_RUN14 == "operator_run_14_sanitized_excerpt"

    def _pred(text: str) -> bool:
        result = detect(text, rules=ACTIVE_SEED_RULES, rule_set_checksum=checksum)
        return is_client_request(
            category=result.category,
            service_profiles=result.service_profiles,
            hard_exclusion=result.hard_exclusion,
        )

    r14_tp = r14_fp = r14_fn = r14_tn = 0
    for sid, text, is_client, prov in r14.iter_run14_regression_samples():
        assert prov == r14.PROVENANCE_RUN14
        assert r14.EVIDENCE_ID_BY_SAMPLE[sid] > 0
        predicted = _pred(text)
        if is_client and predicted:
            r14_tp += 1
        elif not is_client and predicted:
            r14_fp += 1
        elif is_client and not predicted:
            r14_fn += 1
        else:
            r14_tn += 1
        assert predicted is False, sid

    print(
        f"run14_regression tp={r14_tp} fp={r14_fp} fn={r14_fn} tn={r14_tn} "
        f"precision={r14_tp / max(1, r14_tp + r14_fp):.3f} "
        f"recall={r14_tp / max(1, r14_tp + r14_fn):.3f}"
    )
    assert r14_fp == 0
    assert r14_fn == 1
    assert r14_tp == 0

    # Old C* + T* still meet combined ≥80/80 under ru-mvp-3.
    mod = _load_live_fixture()
    tp = fp = fn = tn = 0
    for _sid, text, is_client in mod.iter_labeled_samples():
        predicted = _pred(text)
        if is_client and predicted:
            tp += 1
        elif not is_client and predicted:
            fp += 1
        elif is_client and not predicted:
            fn += 1
        else:
            tn += 1
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    print(
        f"ct_combined_under_ru_mvp_3 tp={tp} fp={fp} fn={fn} tn={tn} "
        f"precision={precision:.3f} recall={recall:.3f}"
    )
    assert precision >= 0.80
    assert recall >= 0.80
    from telegram_lead_discovery.detection.seed import SEED_RULES_RU_MVP_4

    assert any(r.stable_rule_id == "NEG-ADV-016" for r in SEED_RULES_RU_MVP_4)
    assert tuple(r.stable_rule_id for r in ACTIVE_SEED_RULES) == tuple(
        r.stable_rule_id for r in SEED_RULES_RU_MVP_4
    )
