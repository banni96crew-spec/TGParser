"""Daily maintenance jobs (INF cleanup / purge)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.infrastructure.paths import AppPaths
from telegram_lead_discovery.storage.retention import RetentionPurgeResult, run_retention_purge


async def run_daily_purge(
    session: AsyncSession,
    *,
    paths: AppPaths | None = None,
    now: datetime | None = None,
) -> RetentionPurgeResult:
    """04:00 Europe/Moscow purge entrypoint — exports/tmp + approved retention."""
    return await run_retention_purge(session, paths=paths, now=now)
