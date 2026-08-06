"""Pure keyword discovery profile normalization and seed catalog (SRC-017/018)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from telegram_lead_discovery.source_discovery.keyword_profile_seed import (
    SourceScope,
    MIN_QUERY_LEN,
    MAX_QUERY_LEN,
    MAX_POST_QUERIES,
    MIN_POST_QUERIES,
    MAX_DIRECTORY_QUERIES,
    MIN_DIRECTORY_QUERIES,
    MAX_PROFILE_NAME_LEN,
    MAX_EVIDENCE_EXCERPT_CODEPOINTS,
    SEED_PROFILE_NAME,
    SEED_PROFILE_VERSION,
    SEED_POST_QUERIES,
    SEED_DIRECTORY_QUERIES,
    SEED_DIRECTORY_REPLACEMENT_QUERIES,
    SEED_ADDITIONAL_EXCLUSIONS,
)
from telegram_lead_discovery.source_discovery.keyword_profile_normalization import (
    normalize_query,
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
        "directory_replacement_queries": list(SEED_DIRECTORY_REPLACEMENT_QUERIES),
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


from telegram_lead_discovery.source_discovery.keyword_profile_selection import (
    match_additional_exclusion,
    schedule_balanced_query_kinds,
    select_deep_verification_queries,
)


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
    "SEED_DIRECTORY_REPLACEMENT_QUERIES",
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
