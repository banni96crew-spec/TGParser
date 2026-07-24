"""Keyword discovery profile persistence (SRC-017/018, D-055)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_PROFILE_NAME,
    SEED_PROFILE_VERSION,
    NormalizedProfileQueries,
    ProfileValidationError,
    SourceScope,
    build_seed_normalized_profile,
    normalize_profile_queries,
    seed_profile_checksum,
    validate_profile_name,
)
from telegram_lead_discovery.storage.models import (
    KeywordDiscoveryProfile,
    KeywordDiscoveryProfileVersion,
)


class ProfileNotFoundError(LookupError):
    """Raised when a profile or version row is missing."""


class ProfileVersionConflict(Exception):
    """Raised on optimistic current_version mismatch."""


class ProfileSeedMismatchError(RuntimeError):
    """Raised when an existing seed profile does not match the catalog."""


@dataclass(frozen=True, slots=True)
class ProfileWithVersion:
    profile: KeywordDiscoveryProfile
    version: KeywordDiscoveryProfileVersion


def dumps_str_list(items: tuple[str, ...] | list[str]) -> str:
    return json.dumps(list(items), ensure_ascii=False)


def loads_str_list(raw: str) -> tuple[str, ...]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ProfileValidationError("invalid_queries_json")
    return tuple(str(item) for item in data)


def version_as_normalized(row: KeywordDiscoveryProfileVersion) -> NormalizedProfileQueries:
    scope = row.source_scope
    if scope not in ("groups", "channels", "all"):
        raise ProfileValidationError(f"invalid_source_scope:{scope}")
    return NormalizedProfileQueries(
        post_queries=loads_str_list(row.post_queries_json),
        directory_queries=loads_str_list(row.directory_queries_json),
        additional_exclusions=loads_str_list(row.additional_exclusions_json),
        source_scope=scope,
        required_service_profiles=loads_str_list(row.required_service_profiles_json),
    )


def _build_version_row(
    *,
    profile_id: int,
    version: int,
    queries: NormalizedProfileQueries,
    created_at: datetime,
) -> KeywordDiscoveryProfileVersion:
    return KeywordDiscoveryProfileVersion(
        profile_id=profile_id,
        version=version,
        post_queries_json=dumps_str_list(queries.post_queries),
        directory_queries_json=dumps_str_list(queries.directory_queries),
        required_service_profiles_json=dumps_str_list(queries.required_service_profiles),
        additional_exclusions_json=dumps_str_list(queries.additional_exclusions),
        source_scope=queries.source_scope,
        created_at=created_at,
    )


async def get_profile_by_name(
    session: AsyncSession,
    name: str,
) -> KeywordDiscoveryProfile | None:
    result = await session.execute(
        select(KeywordDiscoveryProfile).where(KeywordDiscoveryProfile.name == name)
    )
    return result.scalar_one_or_none()


async def get_profile(session: AsyncSession, profile_id: int) -> KeywordDiscoveryProfile:
    profile = await session.get(KeywordDiscoveryProfile, profile_id)
    if profile is None:
        raise ProfileNotFoundError(f"profile_not_found:{profile_id}")
    return profile


async def get_profile_version(
    session: AsyncSession,
    *,
    profile_id: int,
    version: int,
) -> KeywordDiscoveryProfileVersion:
    result = await session.execute(
        select(KeywordDiscoveryProfileVersion).where(
            KeywordDiscoveryProfileVersion.profile_id == profile_id,
            KeywordDiscoveryProfileVersion.version == version,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ProfileNotFoundError(f"profile_version_not_found:{profile_id}:{version}")
    return row


async def get_current_profile_version(
    session: AsyncSession,
    profile_id: int,
) -> KeywordDiscoveryProfileVersion:
    profile = await get_profile(session, profile_id)
    return await get_profile_version(
        session,
        profile_id=profile.id,
        version=profile.current_version,
    )


async def create_keyword_discovery_profile(
    session: AsyncSession,
    *,
    name: str,
    post_queries: list[str] | tuple[str, ...],
    directory_queries: list[str] | tuple[str, ...] = (),
    additional_exclusions: list[str] | tuple[str, ...] = (),
    source_scope: SourceScope = "all",
    required_service_profiles: list[str] | tuple[str, ...] = (),
) -> ProfileWithVersion:
    """CreateKeywordDiscoveryProfile — profile + immutable version 1."""
    cleaned_name = validate_profile_name(name)
    existing = await get_profile_by_name(session, cleaned_name)
    if existing is not None:
        raise ProfileValidationError(f"profile_name_taken:{cleaned_name}")

    queries = normalize_profile_queries(
        post_queries=post_queries,
        directory_queries=directory_queries,
        additional_exclusions=additional_exclusions,
        source_scope=source_scope,
        required_service_profiles=required_service_profiles,
    )
    now = datetime.now(UTC)
    profile = KeywordDiscoveryProfile(
        name=cleaned_name,
        state="active",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    await session.flush()
    version_row = _build_version_row(
        profile_id=profile.id,
        version=1,
        queries=queries,
        created_at=now,
    )
    session.add(version_row)
    await session.flush()
    return ProfileWithVersion(profile=profile, version=version_row)


async def create_keyword_discovery_profile_version(
    session: AsyncSession,
    *,
    profile_id: int,
    expected_version: int,
    post_queries: list[str] | tuple[str, ...],
    directory_queries: list[str] | tuple[str, ...] = (),
    additional_exclusions: list[str] | tuple[str, ...] = (),
    source_scope: SourceScope = "all",
    required_service_profiles: list[str] | tuple[str, ...] = (),
) -> ProfileWithVersion:
    """CreateKeywordDiscoveryProfileVersion — append-only; never mutates prior versions."""
    profile = await get_profile(session, profile_id)
    if profile.state != "active":
        raise ProfileValidationError(f"profile_not_active:{profile.state}")
    if profile.current_version != expected_version:
        raise ProfileVersionConflict(
            f"profile_version_conflict:expected={expected_version},"
            f"current={profile.current_version}"
        )

    # Prior version row stays untouched (immutable after insert / run reference).
    prior = await get_profile_version(
        session,
        profile_id=profile.id,
        version=profile.current_version,
    )
    prior_snapshot = (
        prior.post_queries_json,
        prior.directory_queries_json,
        prior.additional_exclusions_json,
        prior.required_service_profiles_json,
        prior.source_scope,
    )

    queries = normalize_profile_queries(
        post_queries=post_queries,
        directory_queries=directory_queries,
        additional_exclusions=additional_exclusions,
        source_scope=source_scope,
        required_service_profiles=required_service_profiles,
    )
    now = datetime.now(UTC)
    next_version = profile.current_version + 1
    version_row = _build_version_row(
        profile_id=profile.id,
        version=next_version,
        queries=queries,
        created_at=now,
    )
    session.add(version_row)
    profile.current_version = next_version
    profile.updated_at = now
    await session.flush()

    reloaded_prior = await get_profile_version(
        session,
        profile_id=profile.id,
        version=expected_version,
    )
    if (
        reloaded_prior.post_queries_json,
        reloaded_prior.directory_queries_json,
        reloaded_prior.additional_exclusions_json,
        reloaded_prior.required_service_profiles_json,
        reloaded_prior.source_scope,
    ) != prior_snapshot:
        raise RuntimeError("profile_version_mutated")

    return ProfileWithVersion(profile=profile, version=version_row)


def _seed_matches_catalog(version_row: KeywordDiscoveryProfileVersion) -> bool:
    expected = build_seed_normalized_profile()
    actual = version_as_normalized(version_row)
    return (
        actual.post_queries == expected.post_queries
        and actual.directory_queries == expected.directory_queries
        and actual.additional_exclusions == expected.additional_exclusions
        and actual.source_scope == expected.source_scope
        and actual.required_service_profiles == expected.required_service_profiles
        and version_row.version == SEED_PROFILE_VERSION
    )


async def ensure_seed_keyword_profile(session: AsyncSession) -> ProfileWithVersion:
    """Idempotent seed of immutable ecommerce-development-ru version 1 (SRC-017)."""
    existing = await get_profile_by_name(session, SEED_PROFILE_NAME)
    if existing is not None:
        version_row = await get_profile_version(
            session,
            profile_id=existing.id,
            version=SEED_PROFILE_VERSION,
        )
        if not _seed_matches_catalog(version_row):
            raise ProfileSeedMismatchError(
                f"seed_profile_mismatch:{SEED_PROFILE_NAME}:v{SEED_PROFILE_VERSION}:"
                f"checksum={seed_profile_checksum()}"
            )
        return ProfileWithVersion(profile=existing, version=version_row)

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
