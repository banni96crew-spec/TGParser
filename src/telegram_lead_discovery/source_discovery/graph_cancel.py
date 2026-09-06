"""CancelGraphDiscoveryRun and process-wide run_id Event registry (SRC-057)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.source_discovery.graph_service import JOB_TYPE_GRAPH_DISCOVERY
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunNotFoundError,
    KeywordRunStartError,
    KeywordRunVersionConflict,
)
from telegram_lead_discovery.storage.models import DiscoveryRun, Job

TERMINAL_GRAPH_RUN_STATES = frozenset({"succeeded", "partial", "failed", "cancelled"})
_GRAPH_CANCEL_EVENTS: dict[int, asyncio.Event] = {}


class GraphRunNotFoundError(KeywordRunNotFoundError):
    """Graph run id is missing or not run_type=graph."""


def register_graph_cancel_event(run_id: int) -> asyncio.Event:
    event = _GRAPH_CANCEL_EVENTS.get(run_id)
    if event is None:
        event = asyncio.Event()
        _GRAPH_CANCEL_EVENTS[run_id] = event
    return event


def unregister_graph_cancel_event(run_id: int) -> None:
    _GRAPH_CANCEL_EVENTS.pop(run_id, None)


def graph_cancel_event(run_id: int) -> asyncio.Event | None:
    return _GRAPH_CANCEL_EVENTS.get(run_id)


@dataclass(frozen=True, slots=True)
class CancelGraphDiscoveryResult:
    run: DiscoveryRun
    job: Job | None
    idempotent: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def cancel_graph_discovery_run(
    session: AsyncSession,
    *,
    run_id: int,
    expected_version: int,
) -> CancelGraphDiscoveryResult:
    run = await session.get(DiscoveryRun, run_id)
    if run is None or run.run_type != "graph":
        raise GraphRunNotFoundError(f"graph_run_not_found:{run_id}")
    if run.version != expected_version:
        raise KeywordRunVersionConflict(
            f"run_version_conflict:expected={expected_version},current={run.version}"
        )
    job = await _job_for_run(session, run.id)
    if run.state in TERMINAL_GRAPH_RUN_STATES:
        return CancelGraphDiscoveryResult(run=run, job=job, idempotent=True)
    if run.state not in {"queued", "running", "cancelling"} and not (
        job is not None and job.state == "retry_wait"
    ):
        raise KeywordRunStartError(f"run_not_cancellable:{run.state}")

    now = _utcnow()
    live_worker = graph_cancel_event(run.id) is not None or (
        job is not None and job.state == "running"
    )
    if job is not None and job.cancel_requested_at is None:
        job.cancel_requested_at = now
        job.updated_at = now
    if job is not None and job.state == "retry_wait":
        job.available_at = now
        live_worker = graph_cancel_event(run.id) is not None
    if live_worker:
        run.state = "cancelling"
    else:
        run.state = "cancelled"
        run.finished_at = now
        run.last_error_code = "cancel_requested"
        run.run_termination_reason = "cancelled"
        if job is not None:
            job.state = "cancelled"
            job.lease_until = None
            job.available_at = None
            job.updated_at = now
    run.version += 1
    await session.commit()
    event = graph_cancel_event(run.id)
    if event is not None:
        event.set()
    return CancelGraphDiscoveryResult(run=run, job=job, idempotent=False)


async def _job_for_run(session: AsyncSession, run_id: int) -> Job | None:
    result = await session.execute(
        select(Job).where(
            Job.job_type == JOB_TYPE_GRAPH_DISCOVERY,
            Job.dedupe_key == f"graph-discovery:{run_id}",
        )
    )
    return result.scalar_one_or_none()


__all__ = [
    "CancelGraphDiscoveryResult",
    "GraphRunNotFoundError",
    "cancel_graph_discovery_run",
    "graph_cancel_event",
    "register_graph_cancel_event",
    "unregister_graph_cancel_event",
]
