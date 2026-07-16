"""Unit tests — DET golden fixtures + scoring caps/bands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.detection.seed import SEED_RULES, catalog_checksum
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.scoring.engine import DIMENSION_CAPS, score_detection

GOLDEN = [
    ("Нужно разработать интернет-магазин, бюджет 150 000 ₽.", "direct_order"),
    ("Ищу разработчика Telegram-бота для приёма заказов.", "contractor_search"),
    ("Посоветуйте специалиста по интеграции сайта с CRM.", "recommendation_request"),
    ("Как автоматизировать перенос заказов из магазина в CRM?", "potential_need"),
    ("Вакансия: Python-разработчик в штат, зарплата 200000.", "vacancy"),
    ("Наша команда разрабатывает сайты, скидка до пятницы.", "advertising"),
    ("Гарантированный заработок в крипте, пишите всем.", "spam"),
    ("Сегодня отличная погода.", "irrelevant"),
]


def test_det_a_seed_rules_present() -> None:
    assert len(SEED_RULES) >= 40
    assert catalog_checksum()
    assert all(r.dimension and r.stable_rule_id for r in SEED_RULES)


def test_golden_classification_fixtures() -> None:
    for text, expected in GOLDEN:
        analysis = normalize_message_text(text).analysis_text
        result = detect(analysis)
        assert result.category == expected, (text, result.category, result.matched_rules)


def test_positive_requires_intent_and_service() -> None:
    analysis = normalize_message_text("Нужно сделать что-то срочно.").analysis_text
    result = detect(analysis)
    assert result.category == "irrelevant"
    assert result.is_lead is False


def test_scoring_caps_and_bands() -> None:
    text = "Нужно разработать интернет-магазин, бюджет 150 000 ₽. Срочно, готов оплатить."
    analysis = normalize_message_text(text).analysis_text
    detection = detect(analysis)
    assert detection.is_lead
    published = datetime.now(UTC) - timedelta(minutes=10)
    score = score_detection(
        detection,
        published_at=published,
        source_quality_score=5,
        scored_at=datetime.now(UTC),
    )
    by_dim: dict[str, int] = {}
    for comp in score.components:
        if comp.dimension in DIMENSION_CAPS and comp.dimension != "soft_penalty":
            # capped totals are reflected in score.raw_total construction
            by_dim[comp.dimension] = by_dim.get(comp.dimension, 0) + max(0, comp.value)
    for dim, total in by_dim.items():
        if dim in {"freshness", "source_quality"}:
            assert total <= DIMENSION_CAPS[dim]
    assert score.soft_penalty_total >= -30
    assert 0 <= score.total <= 100
    assert score.band in {"hot", "warm", "cold", "irrelevant"}
    if score.band in {"hot", "warm", "cold"}:
        assert score.create_lead is True


def test_hard_exclusion_scores_irrelevant() -> None:
    text = "Вакансия: Python-разработчик в штат, зарплата 200000."
    analysis = normalize_message_text(text).analysis_text
    detection = detect(analysis)
    score = score_detection(
        detection,
        published_at=datetime.now(UTC),
        source_quality_score=5,
        scored_at=datetime.now(UTC),
    )
    assert score.total == 0
    assert score.band == "irrelevant"
    assert score.create_lead is False


def test_matched_excerpt_cap() -> None:
    analysis = normalize_message_text(
        "Нужно разработать интернет-магазин, бюджет 150 000 ₽."
    ).analysis_text
    result = detect(analysis)
    assert result.matched_rules
    assert all(len(m.matched_excerpt) <= 120 for m in result.matched_rules)
