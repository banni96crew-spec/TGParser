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
    if is_qualified:
        q = await _qualified_evidence_count(ctx)
        if q >= RUNTIME_CONFIG.MAX_QUALIFIED_EVIDENCE_PER_RUN:
            return False
        # Absolute priority: never starve qualified for noise that filled soft total.
        return True
    if total >= RUNTIME_CONFIG.MAX_EVIDENCE_PER_RUN:
        return False
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
    """Early-stop deep verification when gate pass already reachable from DB."""
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
    if quality < RUNTIME_CONFIG.GATE_MIN_QUALITY_SOURCES:
        return False
    evidence = await _load_evidence_records(ctx)
    now = _utcnow()
    ids = [
        ClientRequestIdentity(
            telegram_peer_id=r.source_telegram_id,
            telegram_message_id=r.telegram_message_id,
            normalized_hash=r.normalized_hash,
        )
        for r in evidence
        if r.is_qualified
        and is_within_quality_window(r.published_at, now=now)
        and is_client_request(
            category=r.detection_category,
            service_profiles=r.service_profiles,
            hard_exclusion=r.hard_exclusion,
        )
    ]
    return (
        distinct_client_request_count(ids)
        >= RUNTIME_CONFIG.GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS
    )


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
    distinct_count: int,
    scanned: int,
    window_complete: bool,
    hit_source_cap: bool,
    hit_run_cap: bool,
    stop_reason: str | None,
) -> None:
    status = classify_truth_status(
        distinct_qualified_in_window=distinct_count,
        window_complete=window_complete,
        hit_source_cap=hit_source_cap,
        hit_run_cap=hit_run_cap,
    )
    existing = await ctx.session.execute(
        select(SourceOpportunitySnapshot).where(
            SourceOpportunitySnapshot.run_id == ctx.run.id,
            SourceOpportunitySnapshot.source_telegram_id == telegram_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        meta = await _source_meta_for_telegram_id(ctx, telegram_id)
        username = meta.get("username") or await _username_for_telegram_id(ctx, telegram_id)
        row = SourceOpportunitySnapshot(
            run_id=ctx.run.id,
            source_telegram_id=telegram_id,
            username=username,
            title=str(meta.get("title") or username or str(telegram_id)),
            source_type=str(meta.get("source_type") or "megagroup"),
            public_url=meta.get("public_url") or (f"https://t.me/{username}" if username else None),
            qualified_count=distinct_count,
            truth_status=status,
            verification_scanned_count=scanned,
            verification_stop_reason=stop_reason,
            discovery_channels_json=json.dumps(["source_verification"], ensure_ascii=False),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        ctx.session.add(row)
    else:
        row.truth_status = status
        row.verification_scanned_count = scanned
        row.verification_stop_reason = stop_reason
        if distinct_count > row.qualified_count:
            row.qualified_count = distinct_count
        row.updated_at = _utcnow()
        row.version += 1
    await ctx.session.flush()
    await upsert_presented_suppress(
        ctx.session,
        identity=SuppressIdentity(
            canonical_key=peer_canonical_key(telegram_id),
            telegram_id=telegram_id,
            username_normalized=row.username,
        ),
        origin_run_id=ctx.run.id,
        origin_opportunity_id=row.id,
        first_presented_at=row.created_at,
    )
    """Legacy helper kept for tests; prefer ``_finished_verification_sources``."""
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
            DiscoveryRunQuery.state.in_(tuple(_TERMINAL_VERIFICATION_STATES)),
        )
    )
    keys: set[tuple[int, str]] = set()
    for row in result.scalars():
        if row.source_telegram_id is None:
            continue
        keys.add((row.source_telegram_id, row.query_text))
    return keys
