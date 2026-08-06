"""Seed profile persistence and immutable-catalog verification."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_PROFILE_NAME,
    build_seed_normalized_profile,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    ProfileNotFoundError,
    ProfileSeedMismatchError,
    ProfileValidationError,
    ProfileVersionConflict,
    ProfileWithVersion,
    _build_version_row,
    create_keyword_discovery_profile,
    create_keyword_discovery_profile_version,
    dumps_str_list,
    get_current_profile_version,
    get_profile,
    get_profile_by_name,
    get_profile_version,
    loads_str_list,
    version_as_normalized,
)
from telegram_lead_discovery.storage.models import (
    KeywordDiscoveryProfile,
    KeywordDiscoveryProfileVersion,
)


def _seed_matches_catalog(version_row: KeywordDiscoveryProfileVersion) -> bool:
    expected = build_seed_normalized_profile()
    actual = version_as_normalized(version_row)
    return (
        actual.post_queries == expected.post_queries
        and actual.directory_queries == expected.directory_queries
        and actual.replacement_directory_queries == expected.replacement_directory_queries
        and actual.additional_exclusions == expected.additional_exclusions
        and actual.source_scope == expected.source_scope
        and actual.required_service_profiles == expected.required_service_profiles
    )


async def ensure_seed_keyword_profile(session: AsyncSession) -> ProfileWithVersion:
    """Create immutable clean seed v3 or verify migration-owned operator v7."""
    existing = await get_profile_by_name(session, SEED_PROFILE_NAME)
    if existing is None:
        seed = build_seed_normalized_profile()
        now = datetime.now(UTC)
        profile = KeywordDiscoveryProfile(
            name=SEED_PROFILE_NAME,
            state="active",
            current_version=3,
            created_at=now,
            updated_at=now,
        )
        session.add(profile)
        await session.flush()
        version_row = _build_version_row(
            profile_id=profile.id,
            version=3,
            queries=seed,
            created_at=now,
        )
        session.add(version_row)
        await session.flush()
        return ProfileWithVersion(profile=profile, version=version_row)

    version_row = await get_current_profile_version(session, existing.id)
    if existing.current_version in {3, 7} and _seed_matches_catalog(version_row):
        return ProfileWithVersion(profile=existing, version=version_row)
    raise ProfileSeedMismatchError(
        f"seed_profile_mismatch:current_version={existing.current_version}"
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
