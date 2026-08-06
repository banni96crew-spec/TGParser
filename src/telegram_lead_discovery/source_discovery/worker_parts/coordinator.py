from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *
from telegram_lead_discovery.detection.errors import RuleSetInvalidError
from telegram_lead_discovery.detection.loader import get_default_loader

from telegram_lead_discovery.source_discovery.worker_parts.control import _check_cancel
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _CancelRequested,
    _FloodWaitControl,
    _SessionFatal,
    _WorkerContext,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.finalize import (
    _phase_finalize_opportunities,
)
from telegram_lead_discovery.source_discovery.worker_parts.lifecycle import (
    _fail_run,
    _finish_run,
    _mark_cancelled,
    _park_flood_wait,
)
from telegram_lead_discovery.source_discovery.worker_parts.linked import _phase_linked_discussions
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _load_dismissed_sources,
    _load_presented_sources,
    _load_registry,
)
from telegram_lead_discovery.source_discovery.worker_parts.seed_queries import _run_seed_queries
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _restore_directory_pool,
)
from telegram_lead_discovery.source_discovery.worker_parts.verification_phase import (
    _phase_deep_verification,
)


async def process_keyword_discovery_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    """Execute one claimed ``keyword_discovery`` job to a wait or terminal state."""
    if job.job_type != JOB_TYPE_KEYWORD_DISCOVERY:
        raise ValueError(f"unexpected_job_type:{job.job_type}")

    payload = json.loads(job.payload_json or "{}")
    run_id = int(payload["run_id"])
    run = await session.get(DiscoveryRun, run_id)
    if run is None or run.run_type != "keyword_scouting":
        job.state = "failed"
        job.last_error_code = "run_not_found"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "failed", "error": "run_not_found"}

    if run.state in ("succeeded", "partial", "failed", "cancelled"):
        job.state = "succeeded" if run.state != "failed" else "failed"
        if run.state == "cancelled":
            job.state = "cancelled"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "already_terminal", "run_state": run.state}

    if run.profile_version_id is None:
        return await _fail_run(session, job, run, "profile_version_missing")
    version_row = await session.get(KeywordDiscoveryProfileVersion, run.profile_version_id)
    if version_row is None:
        return await _fail_run(session, job, run, "profile_version_missing")
    if run.rule_set_version_id is None or not run.rule_set_checksum:
        return await _fail_run(session, job, run, "rule_set_pin_missing")
    try:
        catalog = await get_default_loader().load(
            session,
            rule_set_version_id=run.rule_set_version_id,
            checksum=run.rule_set_checksum,
        )
    except RuleSetInvalidError:
        return await _fail_run(session, job, run, "rule_set_pin_invalid")

    normalized = version_as_normalized(version_row)
    registry = await _load_registry(session)
    dismissed = await _load_dismissed_sources(session)
    presented = await _load_presented_sources(session)
    now = _utcnow()
    if run.state in ("queued", "retry_wait_flood", "cancelling"):
        if run.state != "cancelling":
            run.state = "running"
        if run.started_at is None:
            run.started_at = now
        if run.reference_at is None:
            run.reference_at = run.started_at
    run.phase = run.phase or "B"
    await session.flush()

    ctx = _WorkerContext(
        session=session,
        gateway=gateway,
        job=job,
        run=run,
        profile_version=version_row,
        post_queries=normalized.post_queries,
        directory_queries=normalized.directory_queries,
        replacement_directory_queries=normalized.replacement_directory_queries,
        additional_exclusions=normalized.additional_exclusions,
        required_service_profiles=normalized.required_service_profiles,
        detection_rules=catalog.rules,
        rule_set_checksum=catalog.checksum,
        registry=registry,
        dismissed=dismissed,
        directory_sources=[],
        linked_parents={},
        last_heartbeat_at=now,
        presented=presented,
    )

    try:
        await _restore_directory_pool(ctx)
        await _check_cancel(ctx)
        await _run_seed_queries(ctx)
        await _check_cancel(ctx)
        await _phase_linked_discussions(ctx)
        await _check_cancel(ctx)
        await _phase_deep_verification(ctx)
        await _check_cancel(ctx)
        await _phase_finalize_opportunities(ctx)
        return await _finish_run(ctx)
    except _CancelRequested:
        return await _mark_cancelled(ctx)
    except _FloodWaitControl as exc:
        return await _park_flood_wait(ctx, exc)
    except _SessionFatal as exc:
        note_session_fatal(code=exc.code)
        return await _fail_run(session, job, run, exc.code)
