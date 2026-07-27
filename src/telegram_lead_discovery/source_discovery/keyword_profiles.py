"""Pure keyword discovery profile normalization and seed catalog (SRC-017/018)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

SourceScope = Literal["groups", "channels", "all"]

MIN_QUERY_LEN = 3
MAX_QUERY_LEN = 128
MAX_POST_QUERIES = 20
MIN_POST_QUERIES = 1
MAX_DIRECTORY_QUERIES = 10
MIN_DIRECTORY_QUERIES = 0
MAX_PROFILE_NAME_LEN = 80
MAX_EVIDENCE_EXCERPT_CODEPOINTS = 240

SEED_PROFILE_NAME = "ecommerce-development-ru"
SEED_PROFILE_VERSION = 1

SEED_POST_QUERIES: tuple[str, ...] = (
    "нужен разработчик сайта",
    "ищу разработчика сайта",
    "кто сделает сайт",
    "посоветуйте разработчика",
    "нужно разработать сайт",
    "нужен интернет-магазин",
    "разработать интернет-магазин",
    "доработать интернет-магазин",
    "нужен telegram бот",
    "разработать telegram бота",
    "нужен mini app",
    "разработать мобильное приложение",
    "нужна интеграция api",
    "интеграция сайта crm",
    "автоматизировать заказы",
    "нужен парсер",
    "интеграция ozon",
    "интеграция wildberries",
)

SEED_DIRECTORY_QUERIES: tuple[str, ...] = (
    "ecommerce",
    "e-commerce",
    "интернет-магазин",
    "маркетплейсы",
    "ozon",
    "wildberries",
    "бизнес чат",
    "предприниматели",
)

SEED_ADDITIONAL_EXCLUSIONS: tuple[str, ...] = (
    "ищем в команду",
    "резюме",
    "ищу работу",
    "предлагаю услуги",
    "курс",
    "обучение",
)


class ProfileValidationError(ValueError):
    """Raised when profile query/name constraints are violated."""


@dataclass(frozen=True, slots=True)
class NormalizedProfileQueries:
    post_queries: tuple[str, ...]
    directory_queries: tuple[str, ...]
    additional_exclusions: tuple[str, ...]
    source_scope: SourceScope
    required_service_profiles: tuple[str, ...] = ()


def normalize_query(raw: str) -> str:
    """Trim whitespace and casefold a single query string."""
    return raw.strip().casefold()


def truncate_evidence_excerpt(
    text: str,
    *,
    max_codepoints: int = MAX_EVIDENCE_EXCERPT_CODEPOINTS,
) -> str:
    """Cap evidence excerpt by Unicode code points (D-056)."""
    if max_codepoints < 0:
        raise ValueError("max_codepoints must be >= 0")
    if len(text) <= max_codepoints:
        return text
    return text[:max_codepoints]


def _validate_query(normalized: str) -> None:
    length = len(normalized)
    if length < MIN_QUERY_LEN or length > MAX_QUERY_LEN:
        raise ProfileValidationError(
            f"query_length_out_of_range:{length}"
        )


def _dedupe_normalized_queries(raw_queries: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_queries:
        normalized = normalize_query(raw)
        _validate_query(normalized)
        if normalized in seen:
            raise ProfileValidationError(f"duplicate_query:{normalized}")
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _normalize_query_list(
    raw_queries: list[str] | tuple[str, ...],
    *,
    min_count: int,
    max_count: int,
    field: str,
) -> tuple[str, ...]:
    if not (min_count <= len(raw_queries) <= max_count):
        raise ProfileValidationError(f"{field}_count_out_of_range:{len(raw_queries)}")
    return _dedupe_normalized_queries(raw_queries)


def _normalize_unbounded_query_list(
    raw_queries: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    if not raw_queries:
        return ()
    return _dedupe_normalized_queries(raw_queries)


def normalize_profile_queries(
    *,
    post_queries: list[str] | tuple[str, ...],
    directory_queries: list[str] | tuple[str, ...] = (),
    additional_exclusions: list[str] | tuple[str, ...] = (),
    source_scope: SourceScope = "all",
    required_service_profiles: list[str] | tuple[str, ...] = (),
) -> NormalizedProfileQueries:
    """Normalize and validate profile query lists (SRC-018)."""
    if source_scope not in ("groups", "channels", "all"):
        raise ProfileValidationError(f"invalid_source_scope:{source_scope}")

    posts = _normalize_query_list(
        post_queries,
        min_count=MIN_POST_QUERIES,
        max_count=MAX_POST_QUERIES,
        field="post_queries",
    )
    directories = _normalize_query_list(
        directory_queries,
        min_count=MIN_DIRECTORY_QUERIES,
        max_count=MAX_DIRECTORY_QUERIES,
        field="directory_queries",
    )
    # Exclusions share length + casefold-dupe rules; count is unbounded for MVP seed.
    exclusions = _normalize_unbounded_query_list(additional_exclusions)
    services = tuple(normalize_query(s) for s in required_service_profiles)

    return NormalizedProfileQueries(
        post_queries=posts,
        directory_queries=directories,
        additional_exclusions=exclusions,
        source_scope=source_scope,
        required_service_profiles=services,
    )


def seed_profile_payload() -> dict[str, object]:
    """Canonical seed profile document for checksum (SRC-017)."""
    return {
        "name": SEED_PROFILE_NAME,
        "version": SEED_PROFILE_VERSION,
        "source_scope": "all",
        "post_queries": list(SEED_POST_QUERIES),
        "directory_queries": list(SEED_DIRECTORY_QUERIES),
        "additional_exclusions": list(SEED_ADDITIONAL_EXCLUSIONS),
        "required_service_profiles": [],
    }


def seed_profile_canonical_json() -> str:
    return json.dumps(
        seed_profile_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def seed_profile_checksum() -> str:
    """Stable SHA-256 of the immutable seed profile catalog."""
    return hashlib.sha256(seed_profile_canonical_json().encode("utf-8")).hexdigest()


def build_seed_normalized_profile() -> NormalizedProfileQueries:
    return normalize_profile_queries(
        post_queries=SEED_POST_QUERIES,
        directory_queries=SEED_DIRECTORY_QUERIES,
        additional_exclusions=SEED_ADDITIONAL_EXCLUSIONS,
        source_scope="all",
    )


def validate_profile_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_PROFILE_NAME_LEN:
        raise ProfileValidationError(f"profile_name_length_out_of_range:{len(cleaned)}")
    return cleaned


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


__all__ = [
    "MAX_DIRECTORY_QUERIES",
    "MAX_EVIDENCE_EXCERPT_CODEPOINTS",
    "MAX_POST_QUERIES",
    "MAX_PROFILE_NAME_LEN",
    "MAX_QUERY_LEN",
    "MIN_POST_QUERIES",
    "MIN_QUERY_LEN",
    "NormalizedProfileQueries",
    "ProfileValidationError",
    "SEED_ADDITIONAL_EXCLUSIONS",
    "SEED_DIRECTORY_QUERIES",
    "SEED_POST_QUERIES",
    "SEED_PROFILE_NAME",
    "SEED_PROFILE_VERSION",
    "SourceScope",
    "build_seed_normalized_profile",
    "match_additional_exclusion",
    "normalize_profile_queries",
    "normalize_query",
    "schedule_balanced_query_kinds",
    "seed_profile_canonical_json",
    "seed_profile_checksum",
    "seed_profile_payload",
    "select_deep_verification_queries",
    "truncate_evidence_excerpt",
    "validate_profile_name",
]
