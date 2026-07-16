"""Approved retention cleanup (STO-010 / INF daily purge)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.infrastructure.paths import AppPaths, ensure_app_directories
from telegram_lead_discovery.storage.models import NotificationDelivery, NotificationOutbox

EXPORTS_TMP_MAX_AGE = timedelta(hours=1)
TERMINAL_OUTBOX_RETENTION = timedelta(days=30)
TERMINAL_OUTBOX_STATES = frozenset({"sent", "dead"})
BATCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class RetentionPurgeResult:
    exports_tmp_deleted: int
    terminal_outbox_deleted: int
    terminal_deliveries_deleted: int
    duration_ms: int


def purge_exports_and_tmp(
    paths: AppPaths | None = None,
    *,
    now: datetime | None = None,
    max_age: timedelta = EXPORTS_TMP_MAX_AGE,
) -> int:
    """Delete files under exports/ and tmp/ older than max_age (default 1 hour)."""
    resolved = ensure_app_directories(paths)
    clock = now or datetime.now(UTC)
    cutoff = clock - max_age
    deleted = 0
    for directory in (resolved.exports_dir, resolved.tmp_dir):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if mtime < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
    return deleted


async def purge_terminal_notification_rows(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = TERMINAL_OUTBOX_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> tuple[int, int]:
    """Delete terminal outbox rows older than retention together with their deliveries."""
    clock = now or datetime.now(UTC)
    cutoff = clock - retention
    result = await session.execute(
        select(NotificationOutbox.id)
        .where(
            NotificationOutbox.state.in_(tuple(TERMINAL_OUTBOX_STATES)),
            NotificationOutbox.created_at < cutoff,
        )
        .order_by(NotificationOutbox.id.asc())
        .limit(batch_limit)
    )
    outbox_ids = list(result.scalars().all())
    if not outbox_ids:
        return 0, 0
    deliveries = await session.execute(
        delete(NotificationDelivery).where(NotificationDelivery.outbox_id.in_(outbox_ids))
    )
    outboxes = await session.execute(
        delete(NotificationOutbox).where(NotificationOutbox.id.in_(outbox_ids))
    )
    await session.flush()
    return int(outboxes.rowcount or 0), int(deliveries.rowcount or 0)


async def run_retention_purge(
    session: AsyncSession,
    *,
    paths: AppPaths | None = None,
    now: datetime | None = None,
) -> RetentionPurgeResult:
    started = datetime.now(UTC)
    clock = now or started
    files_deleted = purge_exports_and_tmp(paths, now=clock)
    outbox_deleted, deliveries_deleted = await purge_terminal_notification_rows(
        session, now=clock
    )
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return RetentionPurgeResult(
        exports_tmp_deleted=files_deleted,
        terminal_outbox_deleted=outbox_deleted,
        terminal_deliveries_deleted=deliveries_deleted,
        duration_ms=duration_ms,
    )
