from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext, _utcnow
from telegram_lead_discovery.source_discovery.worker_parts.history_state import _load_run_cursor
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _TERMINAL_VERIFICATION_STATES,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _evidence_count,
    _load_evidence_records,
)


async def _persist_acquisition_pool(
    ctx: _WorkerContext,
    *,
    pool: list[dict[str, Any]],
    pool_cursor: int,
) -> None:
    payload = _load_run_cursor(ctx)
    payload["acquisition_pool"] = pool
    payload["acquisition_pool_cursor"] = int(pool_cursor)
    ctx.run.cursor_json = json.dumps(payload, ensure_ascii=False)
    await ctx.session.flush()


async def _source_meta_for_telegram_id(ctx: _WorkerContext, telegram_id: int) -> dict[str, Any]:
    payload = _load_run_cursor(ctx)
    for key in ("acquisition_pool", "directory_pool"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and int(item.get("telegram_id", -1)) == telegram_id:
                return item
    for snap in ctx.directory_sources:
        if snap.telegram_id == telegram_id:
            return {
                "telegram_id": snap.telegram_id,
                "username": snap.username,
                "title": snap.title,
                "source_type": snap.source_type,
                "public_url": snap.public_url,
            }
    opp = await ctx.session.execute(
        select(SourceOpportunitySnapshot).where(
            SourceOpportunitySnapshot.run_id == ctx.run.id,
            SourceOpportunitySnapshot.source_telegram_id == telegram_id,
        )
    )
    row = opp.scalar_one_or_none()
    if row is not None:
        return {
            "telegram_id": telegram_id,
            "username": row.username,
            "title": row.title,
            "source_type": row.source_type,
            "public_url": row.public_url,
        }
    return {"telegram_id": telegram_id}


async def _may_persist_evidence(ctx: _WorkerContext, *, is_qualified: bool) -> bool:
    """Qualified evidence has absolute priority over noise within documented caps."""
    total = await _evidence_count(ctx)
    if total >= RUNTIME_CONFIG.MAX_EVIDENCE_PER_RUN:
        return False
    if is_qualified:
        q = await _qualified_evidence_count(ctx)
        if q >= RUNTIME_CONFIG.MAX_QUALIFIED_EVIDENCE_PER_RUN:
            return False
        return True
    noise = total - await _qualified_evidence_count(ctx)
    return noise < RUNTIME_CONFIG.MAX_NOISE_EVIDENCE_PER_RUN


async def _qualified_evidence_count(ctx: _WorkerContext) -> int:
    result = await ctx.session.execute(
        select(func.count())
        .select_from(SourceDiscoveryEvidence)
        .where(
            SourceDiscoveryEvidence.run_id == ctx.run.id,
            SourceDiscoveryEvidence.is_qualified.is_(True),
        )
    )
    return int(result.scalar_one())


async def _gate_satisfied_from_persisted(ctx: _WorkerContext) -> bool:
    """ActiveClientChat v1 passes as soon as one terminal quality source exists."""
    opp_rows = list(
        (
            await ctx.session.execute(
                select(SourceOpportunitySnapshot).where(
                    SourceOpportunitySnapshot.run_id == ctx.run.id
                )
            )
        ).scalars()
    )
    quality = sum(1 for o in opp_rows if o.truth_status == "quality")
    return quality >= 1


async def _username_for_telegram_id(ctx: _WorkerContext, telegram_id: int) -> str | None:
    opp = await ctx.session.execute(
        select(SourceOpportunitySnapshot).where(
            SourceOpportunitySnapshot.run_id == ctx.run.id,
            SourceOpportunitySnapshot.source_telegram_id == telegram_id,
        )
    )
    row = opp.scalar_one_or_none()
    if row is not None and row.username:
        return row.username
    ev = await ctx.session.execute(
        select(SourceDiscoveryEvidence)
        .where(
            SourceDiscoveryEvidence.run_id == ctx.run.id,
            SourceDiscoveryEvidence.source_telegram_id == telegram_id,
        )
        .limit(1)
    )
    evidence = ev.scalar_one_or_none()
    if evidence is not None and evidence.source_username:
        return evidence.source_username
    reg = ctx.registry.by_telegram_id.get(telegram_id)
    if reg is not None and reg.username_normalized:
        return reg.username_normalized
    return None


async def _apply_source_truth(
    ctx: _WorkerContext,
    *,
    telegram_id: int,
    counters: ActiveChatCounters,
    scanned: int,
    stop_reason: str,
) -> None:
    reference_at = ctx.run.reference_at or ctx.run.started_at
    if reference_at is None:
        raise RuntimeError("active_chat_reference_at_missing")
    evaluation = evaluate_active_client_chat(
        counters,
        reference_at=reference_at,
        stop_reason=stop_reason,  # type: ignore[arg-type]
        required_service_profiles=ctx.required_service_profiles,
    )
    meta = await _source_meta_for_telegram_id(ctx, telegram_id)
    source_type = str(meta.get("source_type") or "megagroup")
    if source_type != "megagroup":
        raise RuntimeError(f"active_chat_requires_megagroup:{source_type}")
    username = meta.get("username") or await _username_for_telegram_id(ctx, telegram_id)
    now = _utcnow()
    existing = await ctx.session.execute(
        select(SourceOpportunitySnapshot).where(
            SourceOpportunitySnapshot.run_id == ctx.run.id,
            SourceOpportunitySnapshot.source_telegram_id == telegram_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = SourceOpportunitySnapshot(
            run_id=ctx.run.id,
            source_telegram_id=telegram_id,
            username=username,
            title=str(meta.get("title") or username or str(telegram_id)),
            source_type=source_type,
            public_url=meta.get("public_url") or (f"https://t.me/{username}" if username else None),
            linked_parent_telegram_id=ctx.linked_parents.get(telegram_id),
            discovery_channels_json=json.dumps(["source_verification"], ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        ctx.session.add(row)
    else:
        row.version += 1
        if telegram_id in ctx.linked_parents:
            row.linked_parent_telegram_id = ctx.linked_parents[telegram_id]
    row.qualified_count = counters.client_request_count
    row.excluded_count = counters.hard_excluded_count
    row.last_qualified_at = counters.latest_client_request_at
    row.truth_status = evaluation.truth_status
    row.verification_scanned_count = scanned
    row.verification_stop_reason = stop_reason
    row.activity_message_count = counters.activity_message_count
    row.activity_active_day_count = counters.activity_active_day_count
    row.activity_distinct_author_count = counters.activity_distinct_author_count
    row.client_request_count = counters.client_request_count
    row.client_request_author_count = counters.client_request_author_count
    row.hard_excluded_count = counters.hard_excluded_count
    row.unknown_author_message_count = counters.unknown_author_message_count
    row.latest_client_request_at = counters.latest_client_request_at
    row.score = evaluation.score
    row.band = evaluation.band
    row.score_components_json = json.dumps(
        evaluation.score_components, ensure_ascii=False, sort_keys=True
    )
    row.qualification_version = "active-client-chat-v1"
    row.qualification_reasons_json = json.dumps(
        evaluation.qualification_reasons, ensure_ascii=False
    )
    row.updated_at = now
    await ctx.session.flush()

    canonical_key = peer_canonical_key(telegram_id)
    outcome_result = await ctx.session.execute(
        select(DiscoveryTerminalOutcome).where(
            DiscoveryTerminalOutcome.run_id == ctx.run.id,
            DiscoveryTerminalOutcome.source_canonical_key == canonical_key,
            DiscoveryTerminalOutcome.terminal_outcome_version == 1,
        )
    )
    outcome = outcome_result.scalar_one_or_none()
    if outcome is None:
        thresholds = evaluation.thresholds
        outcome = DiscoveryTerminalOutcome(
            run_id=ctx.run.id,
            source_canonical_key=canonical_key,
            terminal_outcome_version=1,
            truth_status=evaluation.truth_status,
            verification_stop_reason=stop_reason,
            activity_message_count=counters.activity_message_count,
            activity_active_day_count=counters.activity_active_day_count,
            activity_distinct_author_count=counters.activity_distinct_author_count,
            client_request_count=counters.client_request_count,
            client_request_author_count=counters.client_request_author_count,
            hard_excluded_count=counters.hard_excluded_count,
            unknown_author_message_count=counters.unknown_author_message_count,
            latest_client_request_at=counters.latest_client_request_at,
            threshold_activity_messages=thresholds["activity_messages"],
            threshold_activity_days=thresholds["activity_days"],
            threshold_activity_authors=thresholds["activity_authors"],
            threshold_client_requests=thresholds["client_requests"],
            threshold_client_authors=thresholds["client_authors"],
            threshold_freshness=thresholds["freshness"],
            created_at=now,
        )
        ctx.session.add(outcome)
        await ctx.session.flush()
    elif outcome.truth_status != evaluation.truth_status:
        raise RuntimeError("terminal_outcome_immutable_mismatch")

    await upsert_presented_suppress(
        ctx.session,
        identity=SuppressIdentity(
            canonical_key=canonical_key,
            telegram_id=telegram_id,
            username_normalized=row.username,
        ),
        origin_run_id=ctx.run.id,
        origin_opportunity_id=row.id,
        first_presented_at=now,
    )
