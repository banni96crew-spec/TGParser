"""AT-DET-021: technical employer vacancies are candidates, never exclusions."""

from telegram_lead_discovery.detection.catalog import (
    SEED_RULES_RU_MVP_5,
    SEED_RULES_RU_MVP_6,
)
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect


def _detect(text: str):
    return detect(
        text,
        rules=SEED_RULES_RU_MVP_6,
        rule_set_checksum=catalog_checksum(SEED_RULES_RU_MVP_6),
    )


def test_at_det_021_v6_replaces_only_vacancy_exclusions() -> None:
    v5_without_vacancies = tuple(
        rule for rule in SEED_RULES_RU_MVP_5 if not rule.stable_rule_id.startswith("NEG-VAC-")
    )
    assert SEED_RULES_RU_MVP_6[: len(v5_without_vacancies)] == v5_without_vacancies
    assert [rule.stable_rule_id for rule in SEED_RULES_RU_MVP_6[-6:]] == [
        f"POS-VAC-00{number}" for number in range(1, 7)
    ]


def test_at_det_021_technical_vacancy_is_lead() -> None:
    result = _detect("Вакансия: ищем разработчика Telegram-бота в штат, зарплата от 120000")
    assert result.is_lead is True
    assert result.hard_exclusion is False
    assert "POS-VAC-001" in {rule.stable_rule_id for rule in result.matched_rules}


def test_at_det_021_vacancy_without_supported_service_is_irrelevant() -> None:
    result = _detect("Вакансия: ищем бухгалтера в штат, зарплата от 120000")
    assert result.is_lead is False
    assert result.hard_exclusion is False


def test_at_det_021_provider_advertisement_stays_excluded() -> None:
    result = _detect("Принимаем заказы на Telegram-боты. Вакансия для разработчика")
    assert result.is_lead is False
    assert result.hard_exclusion is True
    assert result.category == "advertising"
