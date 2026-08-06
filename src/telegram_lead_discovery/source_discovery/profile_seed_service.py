"""Seed profile persistence and immutable-catalog verification."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_PROFILE_NAME,
    build_seed_normalized_profile,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    ProfileSeedMismatchError,
    ProfileWithVersion,
    _build_version_row,
    create_keyword_discovery_profile,
    create_keyword_discovery_profile_version,
    get_current_profile_version,
    get_profile_by_name,
    loads_str_list,
    version_as_normalized,
)
from telegram_lead_discovery.storage.models import KeywordDiscoveryProfileVersion


def _seed_matches_catalog(version_row: KeywordDiscoveryProfileVersion) -> bool:
    expected = build_seed_normalized_profile()
    actual = version_as_normalized(version_row)
    return (
        actual.post_queries == expected.post_queries
        and actual.directory_queries == expected.directory_queries
        and actual.additional_exclusions == expected.additional_exclusions
        and actual.source_scope == expected.source_scope
        and actual.required_service_profiles == expected.required_service_profiles
    )


async def ensure_seed_keyword_profile(session: AsyncSession) -> ProfileWithVersion:
    """Idempotent seed of ecommerce-development-ru; appends new version on catalog change."""
    existing = await get_profile_by_name(session, SEED_PROFILE_NAME)
    if existing is None:
        seed = build_seed_normalized_profile()
        return await create_keyword_discovery_profile(
            session,
            name=SEED_PROFILE_NAME,
            post_queries=seed.post_queries,
            directory_queries=seed.directory_queries,
            additional_exclusions=seed.additional_exclusions,
            source_scope=seed.source_scope,
            required_service_profiles=seed.required_service_profiles,
        )

    version_row = await get_current_profile_version(session, existing.id)
    if _seed_matches_catalog(version_row):
        return ProfileWithVersion(profile=existing, version=version_row)

    # Remediation: append immutable version with updated seed catalog (D-068).
    seed = build_seed_normalized_profile()
    return await create_keyword_discovery_profile_version(
        session,
        profile_id=existing.id,
        expected_version=existing.current_version,
        post_queries=seed.post_queries,
        directory_queries=seed.directory_queries,
        additional_exclusions=seed.additional_exclusions,
        source_scope=seed.source_scope,
        required_service_profiles=seed.required_service_profiles,
    )


__all__ = [
    "ProfileNotFoundError",
    "ProfileSeedMismatchError",
    "ProfileValidationError",
    "ProfileVersionConflict",
    "ProfileWithVersion",
    "create_keyword_discovery_profile",
    "create_keyword_discovery_profile_version",
    "dumps_str_list",
    "ensure_seed_keyword_profile",
    "get_current_profile_version",
    "get_profile",
    "get_profile_by_name",
    "get_profile_version",
    "loads_str_list",
    "version_as_normalized",
]
