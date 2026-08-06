"""Keyword discovery run lifecycle helpers (SRC-019/027/028, phase A).

UI CSRF / credentials gating stay at the dashboard boundary; this module owns
the transactional create/cancel of DiscoveryRun + DiscoveryRunQuery + Job.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.detection.seed import seed_active_ruleset
from telegram_lead_discovery.source_discovery.profile_service import (
    ProfileNotFoundError,
    get_current_profile_version,
    get_profile,
    version_as_normalized,
)
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    Job,
)

JOB_TYPE_KEYWORD_DISCOVERY = "keyword_discovery"
ACTIVE_KEYWORD_RUN_STATES = frozenset(
    {"queued", "running", "retry_wait_flood", "cancelling"}
)
TERMINAL_KEYWORD_RUN_STATES = frozenset(
    {"succeeded", "partial", "failed", "cancelled"}
)


class KeywordRunStartError(ValueError):
    """Raised when StartKeywordDiscoveryRun is rejected."""


class KeywordRunNotFoundError(LookupError):
    """Raised when run id is missing or not keyword_scouting."""


class KeywordRunVersionConflict(Exception):
    """Raised on optimistic DiscoveryRun.version mismatch."""


@dataclass(frozen=True, slots=True)
class StartKeywordDiscoveryResult:
    run: DiscoveryRun
    job: Job
    query_count: int


@dataclass(frozen=True, slots=True)
class CancelKeywordDiscoveryResult:
    run: DiscoveryRun
    job: Job | None
    idempotent: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def find_active_keyword_run(session: AsyncSession) -> DiscoveryRun | None:
    result = await session.execute(
        select(DiscoveryRun)
        .where(
            DiscoveryRun.run_type == "keyword_scouting",
            DiscoveryRun.state.in_(tuple(ACTIVE_KEYWORD_RUN_STATES)),
        )
        .order_by(DiscoveryRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _expand_run_queries(
    *,
    run_id: int,
    post_queries: tuple[str, ...],
    directory_queries: tuple[str, ...],
    source_scope: str,
) -> list[DiscoveryRunQuery]:
    """Expand profile queries into DiscoveryRunQuery rows (phases B/C/D)."""
    scopes: list[str] = []
    if source_scope in ("groups", "all"):
        scopes.append("groups")
    if source_scope in ("channels", "all"):
        scopes.append("channels")
    if not scopes:
        scopes = ["groups", "channels"]

    rows: list[DiscoveryRunQuery] = []
    ordinal = 0
    for query_text in post_queries:
        for scope in scopes:
            ordinal += 1
            rows.append(
                DiscoveryRunQuery(
                    run_id=run_id,
                    ordinal=ordinal,
                    query_kind="global_message",
                    query_text=query_text,
                    scope=scope,
                    state="queued",
                )
            )
    for query_text in directory_queries:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="directory",
                query_text=query_text,
                scope=None,
                state="queued",
            )
        )
    for query_text in post_queries:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="public_posts",
                query_text=query_text,
                scope=None,
                state="queued",
            )
        )
    return rows


async def start_keyword_discovery_run(
    session: AsyncSession,
    *,
    profile_id: int,
    credentials_present: bool = True,
) -> StartKeywordDiscoveryResult:
    """Create DiscoveryRun + queries + Job in one transaction (SRC-019).

    Does not perform CSRF or HTTP redirect — callers (UI) add those.
    """
    if not credentials_present:
        raise KeywordRunStartError("telegram_credentials_missing")

    active = await find_active_keyword_run(session)
    if active is not None:
        raise KeywordRunStartError(f"active_keyword_run:{active.id}")

    try:
        profile = await get_profile(session, profile_id)
    except ProfileNotFoundError as exc:
        raise KeywordRunStartError(f"profile_not_found:{profile_id}") from exc
    if profile.state != "active":
        raise KeywordRunStartError(f"profile_not_active:{profile.state}")

    version_row = await get_current_profile_version(session, profile_id)
    queries = version_as_normalized(version_row)

    ruleset = await seed_active_ruleset(session)
    rule_set_version_id = ruleset.id
    rule_set_checksum = ruleset.checksum

    now = _utcnow()
    run = DiscoveryRun(
        run_type="keyword_scouting",
        root_source_ids_json="[]",
        profile_version_id=version_row.id,
        search_mode="free_only",
        rule_set_version_id=rule_set_version_id,
        rule_set_checksum=rule_set_checksum,
        state="queued",
        phase="A",
        counters_json=json.dumps(
            {
                "evidence_count": 0,
                "budget_skipped": 0,
                "window_skipped": 0,
                "quota_skipped_queries": 0,
                "failed_queries": 0,
                "unique_sources": 0,
            },
            ensure_ascii=False,
        ),
        version=1,
        created_at=now,
    )
    session.add(run)
    await session.flush()

    query_rows = _expand_run_queries(
        run_id=run.id,
        post_queries=queries.post_queries,
        directory_queries=queries.directory_queries,
        source_scope=queries.source_scope,
    )
    for row in query_rows:
        session.add(row)
    await session.flush()

    job = await enqueue_job(
        session,
        job_type=JOB_TYPE_KEYWORD_DISCOVERY,
        dedupe_key=f"keyword_discovery:run:{run.id}",
        payload={
            "run_id": run.id,
            "profile_id": profile.id,
            "profile_version_id": version_row.id,
            "correlation_id": str(uuid.uuid4()),
        },
    )
    return StartKeywordDiscoveryResult(
        run=run,
        job=job,
        query_count=len(query_rows),
    )


async def cancel_keyword_discovery_run(
    session: AsyncSession,
    *,
    run_id: int,
    expected_version: int,
) -> CancelKeywordDiscoveryResult:
    """Request cancel: Job.cancel_requested_at + run cancelling (SRC-028)."""
    run = await session.get(DiscoveryRun, run_id)
    if run is None or run.run_type != "keyword_scouting":
        raise KeywordRunNotFoundError(f"keyword_run_not_found:{run_id}")
    if run.version != expected_version:
        raise KeywordRunVersionConflict(
            f"run_version_conflict:expected={expected_version},current={run.version}"
        )
    if run.state in TERMINAL_KEYWORD_RUN_STATES:
        job = await _job_for_run(session, run.id)
        return CancelKeywordDiscoveryResult(run=run, job=job, idempotent=True)
    if run.state not in ACTIVE_KEYWORD_RUN_STATES:
        raise KeywordRunStartError(f"run_not_cancellable:{run.state}")

    now = _utcnow()
    run.state = "cancelling"
    run.version += 1
    job = await _job_for_run(session, run.id)
    if job is not None and job.cancel_requested_at is None:
        job.cancel_requested_at = now
        job.updated_at = now
    await session.flush()
    return CancelKeywordDiscoveryResult(run=run, job=job, idempotent=False)


async def _job_for_run(session: AsyncSession, run_id: int) -> Job | None:
    result = await session.execute(
        select(Job).where(
            Job.job_type == JOB_TYPE_KEYWORD_DISCOVERY,
            Job.dedupe_key == f"keyword_discovery:run:{run_id}",
        )
    )
    return result.scalar_one_or_none()


__all__ = [
    "ACTIVE_KEYWORD_RUN_STATES",
    "CancelKeywordDiscoveryResult",
    "JOB_TYPE_KEYWORD_DISCOVERY",
    "KeywordRunNotFoundError",
    "KeywordRunStartError",
    "KeywordRunVersionConflict",
    "StartKeywordDiscoveryResult",
    "TERMINAL_KEYWORD_RUN_STATES",
    "cancel_keyword_discovery_run",
    "find_active_keyword_run",
    "start_keyword_discovery_run",
]
