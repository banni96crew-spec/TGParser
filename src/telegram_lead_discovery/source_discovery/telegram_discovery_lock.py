"""Shared exclusion contract for Telegram discovery modes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import DiscoveryRun

ACTIVE_TELEGRAM_DISCOVERY_STATES = frozenset(
    {"queued", "running", "retry_wait_flood", "cancelling"}
)
TELEGRAM_DISCOVERY_RUN_TYPES = frozenset({"graph", "keyword_scouting"})


async def find_active_telegram_discovery(
    session: AsyncSession,
) -> DiscoveryRun | None:
    result = await session.execute(
        select(DiscoveryRun)
        .where(
            DiscoveryRun.run_type.in_(tuple(TELEGRAM_DISCOVERY_RUN_TYPES)),
            DiscoveryRun.state.in_(tuple(ACTIVE_TELEGRAM_DISCOVERY_STATES)),
        )
        .order_by(DiscoveryRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def discovery_busy_code(run: DiscoveryRun) -> str:
    return f"telegram_discovery_busy:{run.run_type}:{run.id}"


__all__ = [
    "ACTIVE_TELEGRAM_DISCOVERY_STATES",
    "TELEGRAM_DISCOVERY_RUN_TYPES",
    "discovery_busy_code",
    "find_active_telegram_discovery",
]
