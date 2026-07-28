"""Monitoring coverage query used by the dashboard."""

from __future__ import annotations

import json

from sqlalchemy import select

from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    TelegramSource,
)

MONITORING_COVERAGE_LIMIT = 100
_BACKLOG_JOB_TYPES = frozenset(
    {"initial_backfill", "collector_backfill", "reconciliation"}
)


async def _monitoring_coverage_rows(session) -> list[dict[str, object]]:
    sources = (
        await session.execute(
            select(TelegramSource)
            .where(TelegramSource.lifecycle_state.in_(("monitoring", "paused")))
            .order_by(TelegramSource.id.asc())
            .limit(MONITORING_COVERAGE_LIMIT)
        )
    ).scalars().all()
    if not sources:
        return []
    source_ids = [s.id for s in sources]
    checkpoints = {
        c.source_id: c
        for c in (
            await session.execute(
                select(CollectorCheckpoint).where(
                    CollectorCheckpoint.source_id.in_(source_ids)
                )
            )
        ).scalars().all()
    }
    jobs = (
        await session.execute(
            select(Job).where(
                Job.job_type.in_(tuple(_BACKLOG_JOB_TYPES)),
                Job.state.in_(("queued", "running", "lease_expired", "retry_wait")),
            )
        )
    ).scalars().all()
    backlog_by_source: dict[int, int] = {}
    error_by_source: dict[int, str | None] = {}
    for job in jobs:
        try:
            payload = json.loads(job.payload_json or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        sid = payload.get("source_id")
        if sid is None:
            continue
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            continue
        backlog_by_source[sid_i] = backlog_by_source.get(sid_i, 0) + 1
        if job.last_error_code:
            error_by_source[sid_i] = job.last_error_code
    rows: list[dict[str, object]] = []
    for source in sources:
        cp = checkpoints.get(source.id)
        rows.append(
            {
                "id": source.id,
                "username": source.username_normalized,
                "title": source.title,
                "lifecycle_state": source.lifecycle_state,
                "access_error_code": source.access_error_code,
                "last_checked_at": source.last_checked_at,
                "checkpoint_message_id": (
                    cp.last_committed_message_id if cp is not None else None
                ),
                "checkpoint_published_at": (
                    cp.last_committed_published_at if cp is not None else None
                ),
                "last_reconciled_at": cp.last_reconciled_at if cp is not None else None,
                "backlog_jobs": backlog_by_source.get(source.id, 0),
                "job_error_code": error_by_source.get(source.id)
                or source.access_error_code,
                "has_error": bool(
                    source.access_error_code or error_by_source.get(source.id)
                ),
            }
        )
    return rows
