"""P0: startup must activate ru-mvp-3 via real runtime seed boundary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.detection.seed import (
    SEED_RULES,
    SEED_RULES_RU_MVP_3,
    catalog_checksum,
    seed_ruleset_ru_mvp_1,
)
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.infrastructure.runtime import seed_startup_catalog
from telegram_lead_discovery.source_discovery.keyword_run import start_keyword_discovery_run
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import MonitoringRule, RuleSetVersion


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
async def test_startup_catalog_activates_ru_mvp_3_from_active_v1(db_env) -> None:
    """Real startup boundary: DB with only active ru-mvp-1 → exactly one active=ru-mvp-3."""
    async with session_scope() as session:
        v1 = await seed_ruleset_ru_mvp_1(session)
        assert v1.slug == "ru-mvp-1"
        assert v1.state == "active"
        v1_id = v1.id
        v1_checksum = v1.checksum
        rule_count_v1 = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(MonitoringRule)
                    .where(MonitoringRule.rule_set_version_id == v1_id)
                )
            ).scalar_one()
        )
        assert rule_count_v1 == len(SEED_RULES)

    # Startup path used by run_command start/run (not a direct seed_active_ruleset call).
    async with session_scope() as session:
        await seed_startup_catalog(session)

    async with session_scope() as session:
        versions = list((await session.execute(select(RuleSetVersion))).scalars().all())
        by_slug = {v.slug: v for v in versions}
        assert set(by_slug) == {"ru-mvp-1", "ru-mvp-2", "ru-mvp-3"}
        active = [v for v in versions if v.state == "active"]
        assert len(active) == 1
        assert active[0].slug == "ru-mvp-3"
        assert active[0].checksum == catalog_checksum(SEED_RULES_RU_MVP_3)

        assert by_slug["ru-mvp-1"].state == "retired"
        assert by_slug["ru-mvp-1"].id == v1_id
        assert by_slug["ru-mvp-1"].checksum == v1_checksum
        assert by_slug["ru-mvp-2"].state == "retired"

        v3_rules = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(MonitoringRule)
                    .where(MonitoringRule.rule_set_version_id == active[0].id)
                )
            ).scalar_one()
        )
        assert v3_rules == len(SEED_RULES_RU_MVP_3)

    # Repeated startup is idempotent: no duplicate RuleSetVersion / MonitoringRule rows.
    async with session_scope() as session:
        await seed_startup_catalog(session)

    async with session_scope() as session:
        versions = list((await session.execute(select(RuleSetVersion))).scalars().all())
        assert len(versions) == 3
        active = [v for v in versions if v.state == "active"]
        assert len(active) == 1 and active[0].slug == "ru-mvp-3"
        total_rules = int(
            (await session.execute(select(func.count()).select_from(MonitoringRule))).scalar_one()
        )
        from telegram_lead_discovery.detection.seed import SEED_RULES_RU_MVP_2

        expected_rules = (
            len(SEED_RULES) + len(SEED_RULES_RU_MVP_2) + len(SEED_RULES_RU_MVP_3)
        )
        assert total_rules == expected_rules

        # Discovery run pins active v3 after startup.
        profile = await create_keyword_discovery_profile(
            session,
            name="startup-pin-v3",
            post_queries=["нужен сайт"],
            directory_queries=["pool"],
            source_scope="groups",
        )
        started = await start_keyword_discovery_run(session, profile_id=profile.profile.id)
        assert started.run.rule_set_version_id == active[0].id
        assert started.run.rule_set_checksum == active[0].checksum
        assert started.run.rule_set_checksum == catalog_checksum(SEED_RULES_RU_MVP_3)


@pytest.mark.asyncio
async def test_startup_catalog_checksum_mismatch_fails_loudly(db_env) -> None:
    async with session_scope() as session:
        await seed_startup_catalog(session)
        v3 = (
            await session.execute(
                select(RuleSetVersion).where(RuleSetVersion.slug == "ru-mvp-3")
            )
        ).scalar_one()
        v3.checksum = "0" * 64
        await session.flush()

    async with session_scope() as session:
        with pytest.raises(RuntimeError, match=r"ruleset_checksum_mismatch:ru-mvp-3"):
            await seed_startup_catalog(session)
