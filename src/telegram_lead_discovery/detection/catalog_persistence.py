"""SQLAlchemy persistence for immutable detection catalogs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.detection.catalog import (
    RULE_FLAGS,
    SEED_RULES,
    SEED_RULES_RU_MVP_2,
    SEED_RULES_RU_MVP_3,
    SEED_RULES_RU_MVP_4,
    SeedRule,
)
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.storage.models import MonitoringRule, RuleSetVersion


async def _insert_ruleset(
    session: AsyncSession,
    *,
    version: int,
    slug: str,
    rules: tuple[SeedRule, ...],
    activate: bool,
) -> RuleSetVersion:
    checksum = catalog_checksum(rules)
    existing = await session.execute(select(RuleSetVersion).where(RuleSetVersion.slug == slug))
    row = existing.scalar_one_or_none()
    if row is not None:
        if row.checksum != checksum:
            raise RuntimeError(f"ruleset_checksum_mismatch:{slug}")
        if activate and row.state != "active":
            await session.execute(
                update(RuleSetVersion)
                .where(RuleSetVersion.state == "active")
                .values(state="retired")
            )
            row.state = "active"
            row.activated_at = datetime.now(UTC)
            await session.flush()
        return row

    if activate:
        await session.execute(
            update(RuleSetVersion).where(RuleSetVersion.state == "active").values(state="retired")
        )
    now = datetime.now(UTC)
    version_row = RuleSetVersion(
        version=version,
        slug=slug,
        locale="ru",
        state="active" if activate else "retired",
        checksum=checksum,
        hot_min=70,
        warm_min=50,
        cold_min=30,
        activated_at=now if activate else None,
    )
    session.add(version_row)
    await session.flush()
    for rule in rules:
        rule_checksum = hashlib.sha256(
            json.dumps(
                asdict(rule), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        session.add(
            MonitoringRule(
                rule_set_version_id=version_row.id,
                stable_rule_id=rule.stable_rule_id,
                kind=rule.kind,
                target=rule.target,
                dimension=rule.dimension,
                weight=rule.weight,
                pattern=rule.pattern,
                flags=RULE_FLAGS,
                priority=rule.priority,
                explanation_code=rule.explanation_code,
                enabled=True,
                checksum=rule_checksum,
            )
        )
    await session.flush()
    return version_row


async def seed_ruleset_ru_mvp_1(session: AsyncSession) -> RuleSetVersion:
    """Bootstrap historical ru-mvp-1 without forcing it active after newer catalogs exist."""
    newer = await session.execute(
        select(RuleSetVersion).where(
            RuleSetVersion.slug.in_(("ru-mvp-2", "ru-mvp-3", "ru-mvp-4"))
        )
    )
    activate = newer.scalars().first() is None
    return await _insert_ruleset(
        session,
        version=1,
        slug="ru-mvp-1",
        rules=SEED_RULES,
        activate=activate,
    )


async def seed_ruleset_ru_mvp_2(session: AsyncSession) -> RuleSetVersion:
    """Bootstrap immutable ru-mvp-2; do not force active when ru-mvp-3 exists."""
    await seed_ruleset_ru_mvp_1(session)
    existing_v3 = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.slug.in_(("ru-mvp-3", "ru-mvp-4")))
    )
    activate = existing_v3.scalars().first() is None
    return await _insert_ruleset(
        session,
        version=2,
        slug="ru-mvp-2",
        rules=SEED_RULES_RU_MVP_2,
        activate=activate,
    )


async def seed_ruleset_ru_mvp_3(session: AsyncSession) -> RuleSetVersion:
    await seed_ruleset_ru_mvp_2(session)
    existing_v4 = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.slug == "ru-mvp-4")
    )
    return await _insert_ruleset(
        session,
        version=3,
        slug="ru-mvp-3",
        rules=SEED_RULES_RU_MVP_3,
        activate=existing_v4.scalar_one_or_none() is None,
    )


async def seed_ruleset_ru_mvp_4(session: AsyncSession) -> RuleSetVersion:
    await seed_ruleset_ru_mvp_3(session)
    return await _insert_ruleset(
        session,
        version=4,
        slug="ru-mvp-4",
        rules=SEED_RULES_RU_MVP_4,
        activate=True,
    )


async def get_active_ruleset(session: AsyncSession) -> RuleSetVersion | None:
    result = await session.execute(
        select(RuleSetVersion).where(RuleSetVersion.state == "active").limit(1)
    )
    return result.scalar_one_or_none()


async def seed_active_ruleset(session: AsyncSession) -> RuleSetVersion:
    """Ensure active immutable catalog ru-mvp-4 (DET-019 / D-070)."""
    return await seed_ruleset_ru_mvp_4(session)
