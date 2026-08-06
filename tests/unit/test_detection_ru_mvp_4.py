from __future__ import annotations

import pytest

from telegram_lead_discovery.detection.catalog import (
    ACTIVE_SEED_RULES,
    SEED_RULES_RU_MVP_3,
    SEED_RULES_RU_MVP_4,
)
from telegram_lead_discovery.detection.engine import seed_catalog_detect


def test_v4_keeps_v3_immutable_and_replaces_only_marketplace_service_rule() -> None:
    v3_by_id = {rule.stable_rule_id: rule for rule in SEED_RULES_RU_MVP_3}
    v4_by_id = {rule.stable_rule_id: rule for rule in SEED_RULES_RU_MVP_4}
    assert ACTIVE_SEED_RULES == SEED_RULES_RU_MVP_4
    assert len(v4_by_id) == len(v3_by_id) + 6
    for rule_id, rule in v3_by_id.items():
        if rule_id == "SVC-ECOM-002":
            assert v4_by_id[rule_id].pattern != rule.pattern
        else:
            assert v4_by_id[rule_id] == rule


@pytest.mark.parametrize(
    ("text", "category", "services"),
    [
        ("Нужен сайт для салона красоты", "direct_order", {"websites"}),
        ("Ищу разработчика Telegram-бота для заказов", "contractor_search", {"telegram_bots"}),
        (
            "Посоветуйте специалиста по интеграции сайта с CRM",
            "recommendation_request",
            {"websites", "integrations_api"},
        ),
        ("Нужен парсер для каталога", "direct_order", {"automation_parsers"}),
        ("Нужен интернет-магазин", "direct_order", {"ecommerce"}),
    ],
)
def test_explicit_buyers_across_service_families(text, category, services) -> None:
    result = seed_catalog_detect(text)
    assert result.category == category
    assert services <= set(result.service_profiles)
    assert not result.hard_exclusion


@pytest.mark.parametrize(
    "text",
    [
        "Предлагаю услуги: сайт для бизнеса",
        "Мои кейсы в портфолио: сайт и Telegram бот",
        "Курс по автоматизации Wildberries",
        "Отгрузка заказов Ozon на склад завтра",
    ],
)
def test_provider_training_and_marketplace_operations_are_hard_excluded(text) -> None:
    result = seed_catalog_detect(text)
    assert result.hard_exclusion
    assert result.category in {"advertising", "vacancy"}


@pytest.mark.parametrize(
    "text",
    [
        "Ozon Wildberries маркетплейс доставка",
        "Заказы и поддержка на маркетплейсе",
    ],
)
def test_bare_marketplace_operations_do_not_establish_development_service(text) -> None:
    result = seed_catalog_detect(text)
    assert "ecommerce" not in result.service_profiles
    assert not result.is_lead


def test_explicit_marketplace_technical_order_keeps_ecommerce_service() -> None:
    result = seed_catalog_detect("Нужна интеграция API с Ozon")
    assert result.category == "direct_order"
    assert {"integrations_api", "ecommerce"} <= set(result.service_profiles)
    assert not result.hard_exclusion
