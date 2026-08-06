"""Deep-query selection and balanced scheduling policy."""

from telegram_lead_discovery.source_discovery.keyword_profile_normalization import (
    normalize_query,
)


# Service-code → query substrings used to prefer profile-bound deep queries (SRC-024/045).
_SERVICE_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "ecommerce": ("магазин", "ecommerce", "e-commerce", "ozon", "wildberries", "маркетплейс"),
    "bot": ("бот", "telegram бот", "mini app"),
    "web": ("сайт", "разработчик", "интеграция"),
    "mobile": ("мобильн", "приложение"),
    "parser": ("парсер",),
}


def match_additional_exclusion(
    text: str,
    exclusions: list[str] | tuple[str, ...],
) -> str | None:
    """Return explainable reason when text matches a profile additional exclusion."""
    folded = text.casefold()
    for raw in exclusions:
        phrase = normalize_query(raw) if raw.strip() else ""
        if phrase and phrase in folded:
            return f"profile_additional_exclusion:{phrase}"
    return None


def select_deep_verification_queries(
    post_queries: list[str] | tuple[str, ...],
    *,
    required_service_profiles: list[str] | tuple[str, ...] = (),
    limit: int = 5,
) -> tuple[str, ...]:
    """Pick ≤limit profile queries for deep verification (not naive ``post_queries[:5]``).

    When ``required_service_profiles`` is set, prefer queries matching those services.
    Otherwise stride-sample across the full post query list for diversity (SRC-024).

    """
    if limit <= 0 or not post_queries:
        return ()
    posts = tuple(post_queries)
    services = tuple(normalize_query(s) for s in required_service_profiles if s.strip())

    preferred: list[str] = []
    if services:
        hints: list[str] = []
        for svc in services:
            hints.extend(_SERVICE_QUERY_HINTS.get(svc, (svc,)))
        for query in posts:
            folded = query.casefold()
            if any(h in folded for h in hints):
                preferred.append(query)
            if len(preferred) >= limit:
                return tuple(preferred[:limit])

    # Fill remainder (or full selection) via stride sampling — avoids fixed prefix bias.
    remaining = [q for q in posts if q not in preferred]
    if not remaining and preferred:
        return tuple(preferred[:limit])
    need = limit - len(preferred)
    if need <= 0:
        return tuple(preferred[:limit])
    if len(remaining) <= need:
        return tuple([*preferred, *remaining][:limit])
    stride = max(1, len(remaining) // need)
    sampled: list[str] = []
    for i in range(0, len(remaining), stride):
        sampled.append(remaining[i])
        if len(sampled) >= need:
            break
    # If stride undershoots, append from the end.
    if len(sampled) < need:
        for q in reversed(remaining):
            if q not in sampled:
                sampled.append(q)
            if len(sampled) >= need:
                break
    return tuple([*preferred, *sampled][:limit])


def schedule_balanced_query_kinds(
    *,
    post_count: int,
    directory_count: int,
    include_public_posts: bool = True,
) -> tuple[str, ...]:
    """Interleave global / directory / public_posts kinds for balanced seed scheduling."""
    posts = max(0, post_count)
    dirs = max(0, directory_count)
    pub = posts if include_public_posts else 0
    kinds: list[str] = []
    pi = di = ui = 0
    # Round-robin across available lanes so directory is not starved behind all globals.
    while pi < posts or di < dirs or ui < pub:
        if pi < posts:
            kinds.append("global_message")
            pi += 1
        if di < dirs:
            kinds.append("directory")
            di += 1
        if ui < pub:
            kinds.append("public_posts")
            ui += 1
    return tuple(kinds)
