"""Deterministic pre-quota filter for service-provider directory results."""

from __future__ import annotations

import re

PROVIDER_OFFER_TOKENS = (
    "агентство",
    "веб-студия",
    "веб студия",
    "разработчик",
    "разработчики",
    "разработка сайтов",
    "создание сайтов",
    "делаем сайты",
    "сделаем сайт",
    "фрилансер",
    "фрилансеры",
    "программист",
    "программисты",
    "вебмастер",
    "вебмастеры",
    "услуги разработки",
    "разработка под ключ",
    "webstudio",
    "web studio",
    "webdev",
    "devchat",
    "freelance",
)


def directory_candidate_exclusion_reason(
    *, title: str, username: str | None,
) -> str | None:
    haystack = " ".join((title, username or "")).casefold().replace("_", " ")
    normalized = re.sub(r"\s+", " ", haystack)
    for token in PROVIDER_OFFER_TOKENS:
        if token in normalized:
            return f"provider_offer_token:{token}"
    return None


__all__ = ["PROVIDER_OFFER_TOKENS", "directory_candidate_exclusion_reason"]
