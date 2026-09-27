"""AT-DET-022: role-first classification prevents provider offers as leads."""

from telegram_lead_discovery.detection.catalog import SEED_RULES_RU_MVP_7
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect


def _detect(text: str):
    return detect(
        text,
        rules=SEED_RULES_RU_MVP_7,
        rule_set_checksum=catalog_checksum(SEED_RULES_RU_MVP_7),
    )


def test_at_det_022_provider_offer_with_generic_task_phrase_is_advertising() -> None:
    result = _detect(
        """Всем привет! Меня зовут Миша.
        Моя задача — сделать так, чтобы вы могли сосредоточиться на росте бизнеса,
        а я возьму на себя всю техническую часть: настройку вебинаров,
        автоматизацию и техническое сопровождение."""
    )
    assert result.category == "advertising"
    assert result.is_lead is False
    assert result.hard_exclusion is True
    assert result.author_role == "provider_offer"
    assert result.hard_exclusion_rule_id == "ROLE-PRO-001"


def test_at_det_022_true_client_request_stays_a_lead() -> None:
    result = _detect("Нужен Telegram-бот для записи клиентов, бюджет 150000")
    assert result.category == "direct_order"
    assert result.is_lead is True
    assert result.author_role == "client_request"


def test_at_det_022_explicit_technical_vacancy_is_not_excluded() -> None:
    result = _detect("Вакансия: ищем разработчика Telegram-бота в штат, зарплата от 120000")
    assert result.category == "vacancy"
    assert result.is_lead is True
    assert result.hard_exclusion is False
    assert result.author_role == "vacancy"


def test_at_det_022_provider_quote_does_not_override_current_client_request() -> None:
    result = _detect(
        "> Моя задача — сделать сайт, а я возьму на себя всю техническую часть.\n"
        "Нужен разработчик Telegram-бота для записи клиентов."
    )
    assert result.category == "direct_order"
    assert result.is_lead is True
    assert result.author_role == "client_request"
