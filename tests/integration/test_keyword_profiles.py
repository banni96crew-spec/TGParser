"""Integration — keyword discovery profile service + seed (AT-SRC-017/018)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_ADDITIONAL_EXCLUSIONS,
    SEED_DIRECTORY_QUERIES,
    SEED_POST_QUERIES,
    SEED_PROFILE_NAME,
    SEED_PROFILE_VERSION,
    ProfileValidationError,
    build_seed_normalized_profile,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    ProfileVersionConflict,
    create_keyword_discovery_profile,
    create_keyword_discovery_profile_version,
    ensure_seed_keyword_profile,
    get_profile_version,
    version_as_normalized,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import DiscoveryRun, KeywordDiscoveryProfile


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    db_path = database_path()
    upgrade_head(db_path)
    await init_engine(db_path)
    yield db_path
    await dispose_engine()


@pytest.mark.asyncio
async def test_at_src_017_seed_ecommerce_development_ru(db_env) -> None:
    async with session_scope() as session:
        first = await ensure_seed_keyword_profile(session)
        second = await ensure_seed_keyword_profile(session)

    assert first.profile.id == second.profile.id
    assert first.version.id == second.version.id
    assert first.profile.name == SEED_PROFILE_NAME
    assert first.profile.state == "active"
    assert first.profile.current_version == SEED_PROFILE_VERSION
    assert first.version.version == SEED_PROFILE_VERSION

    expected = build_seed_normalized_profile()
    actual = version_as_normalized(first.version)
    assert actual.post_queries == expected.post_queries == SEED_POST_QUERIES
    assert actual.directory_queries == expected.directory_queries == SEED_DIRECTORY_QUERIES
    assert (
        actual.additional_exclusions
        == expected.additional_exclusions
        == SEED_ADDITIONAL_EXCLUSIONS
    )
    assert actual.source_scope == "all"
    assert len(actual.post_queries) == 18
    assert len(actual.directory_queries) == 8
    assert len(actual.additional_exclusions) == 6

    async with session_scope() as session:
        rows = list(
            (
                await session.execute(select(KeywordDiscoveryProfile))
            ).scalars().all()
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_profile_normalizes_and_rejects_invalid(db_env) -> None:
    async with session_scope() as session:
        created = await create_keyword_discovery_profile(
            session,
            name="  Custom Profile  ",
            post_queries=["  Нужен Сайт  ", "ищу бота"],
            directory_queries=["Ecommerce"],
            additional_exclusions=[" Курс "],
            source_scope="groups",
        )
        assert created.profile.name == "Custom Profile"
        assert created.version.version == 1
        normalized = version_as_normalized(created.version)
        assert normalized.post_queries == ("нужен сайт", "ищу бота")
        assert normalized.directory_queries == ("ecommerce",)
        assert normalized.additional_exclusions == ("курс",)
        assert normalized.source_scope == "groups"

        with pytest.raises(ProfileValidationError, match="profile_name_taken"):
            await create_keyword_discovery_profile(
                session,
                name="Custom Profile",
                post_queries=["нужен сайт"],
            )

        with pytest.raises(ProfileValidationError, match="duplicate_query"):
            await create_keyword_discovery_profile(
                session,
                name="Other",
                post_queries=["Нужен сайт", "  нужен сайт  "],
            )

        with pytest.raises(ProfileValidationError, match="post_queries_count_out_of_range"):
            await create_keyword_discovery_profile(
                session,
                name="Empty Posts",
                post_queries=[],
            )


@pytest.mark.asyncio
async def test_at_src_018_new_version_leaves_prior_immutable(db_env) -> None:
    async with session_scope() as session:
        created = await create_keyword_discovery_profile(
            session,
            name="mutable-demo",
            post_queries=["нужен сайт", "ищу бота"],
            directory_queries=["ecommerce"],
            source_scope="all",
        )
        profile_id = created.profile.id
        v1_id = created.version.id
        v1_posts = created.version.post_queries_json

        # Simulate a run referencing version 1 (D-055 immutability).
        session.add(
            DiscoveryRun(
                run_type="keyword_scouting",
                profile_version_id=v1_id,
                search_mode="free_only",
                state="succeeded",
            )
        )
        await session.flush()

        with pytest.raises(ProfileVersionConflict, match="profile_version_conflict"):
            await create_keyword_discovery_profile_version(
                session,
                profile_id=profile_id,
                expected_version=0,
                post_queries=["нужен парсер"],
            )

        updated = await create_keyword_discovery_profile_version(
            session,
            profile_id=profile_id,
            expected_version=1,
            post_queries=["нужен парсер", "интеграция ozon"],
            directory_queries=["ozon"],
            additional_exclusions=["резюме"],
            source_scope="channels",
        )
        assert updated.profile.current_version == 2
        assert updated.version.version == 2
        assert updated.version.id != v1_id

        v1 = await get_profile_version(session, profile_id=profile_id, version=1)
        assert v1.id == v1_id
        assert v1.post_queries_json == v1_posts
        assert version_as_normalized(v1).post_queries == ("нужен сайт", "ищу бота")

        v2 = version_as_normalized(updated.version)
        assert v2.post_queries == ("нужен парсер", "интеграция ozon")
        assert v2.directory_queries == ("ozon",)
        assert v2.additional_exclusions == ("резюме",)
        assert v2.source_scope == "channels"
