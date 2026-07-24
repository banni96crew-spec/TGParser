"""Approved retention cleanup (STO-010 / STO-016 / INF daily purge)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.infrastructure.paths import AppPaths, ensure_app_directories
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    NotificationDelivery,
    NotificationOutbox,
    SourceDiscoveryEvent,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)

EXPORTS_TMP_MAX_AGE = timedelta(hours=1)
TERMINAL_OUTBOX_RETENTION = timedelta(days=30)
TERMINAL_OUTBOX_STATES = frozenset({"sent", "dead"})
BATCH_LIMIT = 500

EVIDENCE_EXCERPT_RETENTION = timedelta(days=30)
EVIDENCE_ROW_RETENTION = timedelta(days=90)
UNPROMOTED_SNAPSHOT_RETENTION = timedelta(days=90)
KEYWORD_QUERY_RETENTION = timedelta(days=90)
TERMINAL_KEYWORD_RUN_RETENTION = timedelta(days=90)

KEYWORD_SCOUTING_RUN_TYPE = "keyword_scouting"
TERMINAL_KEYWORD_RUN_STATES = frozenset({"succeeded", "partial", "failed", "cancelled"})

# Dashboard copy when evidence was purged (wired in UI later; SRC-030 / STO-016).
EVIDENCE_RETENTION_UI_MESSAGE = "Доказательства очищены по retention policy"


@dataclass(frozen=True, slots=True)
class RetentionPurgeResult:
    exports_tmp_deleted: int
    terminal_outbox_deleted: int
    terminal_deliveries_deleted: int
    evidence_excerpts_cleared: int
    evidence_rows_deleted: int
    unpromoted_snapshots_deleted: int
    keyword_queries_deleted: int
    terminal_keyword_runs_deleted: int
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


async def _purge_batches(
    session: AsyncSession,
    *,
    batch_limit: int,
    purge_once,
) -> int:
    """Continue batch deletes/updates until a batch returns 0 (STO §11 continuation)."""
    total = 0
    while True:
        n = await purge_once(session, batch_limit=batch_limit)
        total += n
        if n == 0:
            return total
        if n < batch_limit:
            return total


async def clear_evidence_excerpts(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = EVIDENCE_EXCERPT_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Clear SourceDiscoveryEvidence.excerpt older than retention (default 30d)."""
    clock = now or datetime.now(UTC)
    cutoff = clock - retention

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(SourceDiscoveryEvidence.id)
            .where(
                SourceDiscoveryEvidence.created_at < cutoff,
                SourceDiscoveryEvidence.excerpt != "",
            )
            .order_by(SourceDiscoveryEvidence.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        updated = await session.execute(
            update(SourceDiscoveryEvidence)
            .where(SourceDiscoveryEvidence.id.in_(ids))
            .values(excerpt="")
        )
        await session.flush()
        return int(updated.rowcount or 0)

    return await _purge_batches(session, batch_limit=batch_limit, purge_once=_once)


async def purge_empty_evidence_rows(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = EVIDENCE_ROW_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Delete evidence rows without text older than retention (default 90d)."""
    clock = now or datetime.now(UTC)
    cutoff = clock - retention

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(SourceDiscoveryEvidence.id)
            .where(
                SourceDiscoveryEvidence.created_at < cutoff,
                SourceDiscoveryEvidence.excerpt == "",
            )
            .order_by(SourceDiscoveryEvidence.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        deleted = await session.execute(
            delete(SourceDiscoveryEvidence).where(SourceDiscoveryEvidence.id.in_(ids))
        )
        await session.flush()
        return int(deleted.rowcount or 0)

    return await _purge_batches(session, batch_limit=batch_limit, purge_once=_once)


async def purge_unpromoted_opportunity_snapshots(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = UNPROMOTED_SNAPSHOT_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Delete unpromoted opportunity snapshots older than retention (default 90d)."""
    clock = now or datetime.now(UTC)
    cutoff = clock - retention

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(SourceOpportunitySnapshot.id)
            .where(
                SourceOpportunitySnapshot.created_at < cutoff,
                SourceOpportunitySnapshot.promoted_source_id.is_(None),
            )
            .order_by(SourceOpportunitySnapshot.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        deleted = await session.execute(
            delete(SourceOpportunitySnapshot).where(SourceOpportunitySnapshot.id.in_(ids))
        )
        await session.flush()
        return int(deleted.rowcount or 0)

    return await _purge_batches(session, batch_limit=batch_limit, purge_once=_once)


async def purge_keyword_discovery_queries(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = KEYWORD_QUERY_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Delete keyword DiscoveryRunQuery rows older than retention (default 90d)."""
    clock = now or datetime.now(UTC)
    cutoff = clock - retention
    age_ts = func.coalesce(
        DiscoveryRunQuery.finished_at,
        DiscoveryRun.finished_at,
        DiscoveryRun.created_at,
    )

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(DiscoveryRunQuery.id)
            .join(DiscoveryRun, DiscoveryRun.id == DiscoveryRunQuery.run_id)
            .where(
                DiscoveryRun.run_type == KEYWORD_SCOUTING_RUN_TYPE,
                age_ts < cutoff,
            )
            .order_by(DiscoveryRunQuery.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        deleted = await session.execute(
            delete(DiscoveryRunQuery).where(DiscoveryRunQuery.id.in_(ids))
        )
        await session.flush()
        return int(deleted.rowcount or 0)

    return await _purge_batches(session, batch_limit=batch_limit, purge_once=_once)


async def purge_terminal_keyword_runs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention: timedelta = TERMINAL_KEYWORD_RUN_RETENTION,
    batch_limit: int = BATCH_LIMIT,
) -> int:
    """Delete terminal keyword DiscoveryRun rows older than retention (default 90d).

    Runs that still have FK dependents (promoted snapshots, remaining evidence/queries,
    or SourceDiscoveryEvent provenance) are skipped until dependents are gone or retained
    by policy. ``KeywordDiscoveryProfileVersion`` rows are never auto-deleted (STO-016).
    """
    clock = now or datetime.now(UTC)
    cutoff = clock - retention
    run_age = func.coalesce(DiscoveryRun.finished_at, DiscoveryRun.created_at)
    blocked = or_(
        exists().where(SourceDiscoveryEvidence.run_id == DiscoveryRun.id),
        exists().where(SourceOpportunitySnapshot.run_id == DiscoveryRun.id),
        exists().where(DiscoveryRunQuery.run_id == DiscoveryRun.id),
        exists().where(SourceDiscoveryEvent.run_id == DiscoveryRun.id),
    )

    async def _once(session: AsyncSession, *, batch_limit: int) -> int:
        result = await session.execute(
            select(DiscoveryRun.id)
            .where(
                DiscoveryRun.run_type == KEYWORD_SCOUTING_RUN_TYPE,
                DiscoveryRun.state.in_(tuple(TERMINAL_KEYWORD_RUN_STATES)),
                run_age < cutoff,
                ~blocked,
            )
            .order_by(DiscoveryRun.id.asc())
            .limit(batch_limit)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        deleted = await session.execute(delete(DiscoveryRun).where(DiscoveryRun.id.in_(ids)))
        await session.flush()
        return int(deleted.rowcount or 0)

    return await _purge_batches(session, batch_limit=batch_limit, purge_once=_once)


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
    excerpts_cleared = await clear_evidence_excerpts(session, now=clock)
    evidence_deleted = await purge_empty_evidence_rows(session, now=clock)
    snapshots_deleted = await purge_unpromoted_opportunity_snapshots(session, now=clock)
    queries_deleted = await purge_keyword_discovery_queries(session, now=clock)
    runs_deleted = await purge_terminal_keyword_runs(session, now=clock)
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return RetentionPurgeResult(
        exports_tmp_deleted=files_deleted,
        terminal_outbox_deleted=outbox_deleted,
        terminal_deliveries_deleted=deliveries_deleted,
        evidence_excerpts_cleared=excerpts_cleared,
        evidence_rows_deleted=evidence_deleted,
        unpromoted_snapshots_deleted=snapshots_deleted,
        keyword_queries_deleted=queries_deleted,
        terminal_keyword_runs_deleted=runs_deleted,
        duration_ms=duration_ms,
    )
