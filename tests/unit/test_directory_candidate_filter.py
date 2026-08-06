from telegram_lead_discovery.source_discovery.directory_filter import (
    directory_candidate_exclusion_reason,
)


def test_provider_directory_candidates_are_excluded_with_reason() -> None:
    assert directory_candidate_exclusion_reason(
        title="Веб-студия — создание сайтов под ключ",
        username="best_webstudio",
    ) == "provider_offer_token:веб-студия"


def test_client_community_directory_candidate_is_kept() -> None:
    assert directory_candidate_exclusion_reason(
        title="Предприниматели Москвы — деловой чат",
        username="business_moscow_chat",
    ) is None
