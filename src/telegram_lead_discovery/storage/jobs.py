"""Persisted job claim, heartbeat, and lease recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import Job

LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 60
_IN_FLIGHT_DISCOVERY_JOB_IDS: set[int] = set()


def mark_inflight_discovery_job(job_id: int) -> None:
    """STO-025: record that this process owns a running discovery job."""
    _IN_FLIGHT_DISCOVERY_JOB_IDS.add(int(job_id))


def drop_inflight_discovery_job(job_id: int) -> None:
    _IN_FLIGHT_DISCOVERY_JOB_IDS.discard(int(job_id))


def inflight_discovery_job_ids() -> frozenset[int]:
    return frozenset(_IN_FLIGHT_DISCOVERY_JOB_IDS)


async def claim_job(session: AsyncSession, *, job_types: list[str], owner: str) -> Job | None:
    """Claim next queued/retry_wait job, or reclaim an expired running lease (STO-018)."""
    now = datetime.now(UTC)
    # Reclaim expired leases first so kill/restart mid-batch restores work.
    await recover_stale_jobs(session)
    stmt = (
        select(Job)
        .where(
            Job.job_type.in_(job_types),
            Job.state.in_(("queued", "retry_wait")),
            or_(Job.available_at.is_(None), Job.available_at <= now),
        )
        .order_by(Job.id.asc())
        .limit(1)
    )
    try:
        result = await session.execute(stmt.with_for_update(skip_locked=True))
        job = result.scalar_one_or_none()
    except Exception:
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
    if job is None:
        return None
    job.state = "running"
    job.attempt += 1
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.updated_at = now
    job.last_error_code = None
    # owner is retained for heartbeat diagnostics (lease_owner column not on Job).
    _ = owner
    await session.flush()
    return job


async def heartbeat_job(session: AsyncSession, job: Job) -> None:
    job.lease_until = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    job.updated_at = datetime.now(UTC)
    await session.flush()


async def recover_stale_jobs(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    result = await session.execute(
        select(Job).where(
            Job.state == "running",
            Job.lease_until.is_not(None),
            Job.lease_until < now,
        )
    )
    count = 0
    for job in result.scalars():
        if job.job_type == "discovery" and job.id in _IN_FLIGHT_DISCOVERY_JOB_IDS:
            continue
        # #region agent log
        import json as _json, time as _time
        from pathlib import Path as _Path
        try:
            with _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log").open(
                "a", encoding="utf-8"
            ) as _f:
                _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H5","location":"jobs.py:recover_stale_jobs","message":"requeue_stale","data":{"job_id":job.id,"job_type":job.job_type,"inflight":job.id in _IN_FLIGHT_DISCOVERY_JOB_IDS},"timestamp":int(_time.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
        job.state = "queued"
        job.lease_until = None
        job.updated_at = now
        count += 1
    await session.flush()
    return count


async def enqueue_job(
    session: AsyncSession,
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict | None = None,
) -> Job:
    existing = await session.execute(select(Job).where(Job.dedupe_key == dedupe_key))
    job = existing.scalar_one_or_none()
    if job is not None:
        return job
    now = datetime.now(UTC)
    job = Job(
        job_type=job_type,
        dedupe_key=dedupe_key,
        state="queued",
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()
    return job
