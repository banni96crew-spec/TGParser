from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _loads_counters,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import (
    _note_presented_suppressed,
    _upsert_opportunity,
)
from telegram_lead_discovery.source_discovery.worker_parts.registry import _presented_canonical_id
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _load_evidence_records,
    _opportunity_count,
)


async def _phase_finalize_opportunities(ctx: _WorkerContext) -> None:
    ctx.run.phase = "I"
    await ctx.session.flush()
    evidence_rows = await _load_evidence_records(ctx)
    scored_at = _utcnow()
    if not evidence_rows:
        # Keep linked-discussion opportunities already written; still emit gate truth.
        counters = _loads_counters(ctx.run.counters_json)
        counters["evidence_count"] = 0
        counters["unique_sources"] = await _opportunity_count(ctx)
        await _write_gate_counters(ctx, evidence_rows=[], scored_at=scored_at, base=counters)
        return

    # Rebuild annotated hits from persisted evidence is unnecessary — rescore
    # by grouping existing evidence rows into opportunity snapshots.
    by_source: dict[int, list[EvidenceRecord]] = {}
    for row in evidence_rows:
        by_source.setdefault(row.source_telegram_id, []).append(row)

    qualified = 0
    presented = 0
    novel_presented = 0
    qualified_total = 0
    presented_skipped = 0
    for telegram_id, rows in by_source.items():
        presented_id = _presented_canonical_id(
            ctx,
            telegram_id=telegram_id,
            username=rows[0].source_username,
        )
        if presented_id is not None:
            await _note_presented_suppressed(ctx, {presented_id})
            presented_skipped += 1
            continue
        meta = rows[0]
        source = SourceSnapshot(
            schema_version=1,
            telegram_id=telegram_id,
            username=meta.source_username or "",
            title=meta.source_title,
            source_type=meta.source_type,  # type: ignore[arg-type]
            public_url=(f"https://t.me/{meta.source_username}" if meta.source_username else None),
            accessible=True,
        )
        identity = ctx.registry.by_telegram_id.get(telegram_id)
        snap = build_opportunity_from_evidence(
            run_id=ctx.run.id,
            source=source,
            evidence=rows,
            scored_at=scored_at,
            registry_source_id=identity.source_id if identity else None,
            linked_parent_telegram_id=ctx.linked_parents.get(telegram_id),
            required_service_profiles=ctx.required_service_profiles,
            additional_exclusions=ctx.additional_exclusions,
        )
        await _upsert_opportunity(ctx, snap)
        record_score(band=snap.band)
        q_count = sum(1 for row in rows if row.is_qualified)
        qualified += q_count
        if snap.band in ("review", "promising") or snap.qualified_count > 0:
            qualified_total += 1
        presented += 1
        if telegram_id not in ctx.presented.by_telegram_id:
            novel_presented += 1

    record_qualified_evidence(qualified)
    unique_presented_suppress = len(ctx.presented_suppressed_ids)
    counters = merge_funnel_counters(
        _loads_counters(ctx.run.counters_json),
        canonicalized_total=len(by_source) + presented_skipped,
        dismissed_suppressed=len(ctx.dismissed_suppressed_ids),
        presented_suppressed=unique_presented_suppress,
        cooldown_suppressed=unique_presented_suppress,
        qualified_total=qualified_total,
        presented_total=presented,
        novel_presented_total=novel_presented,
    )
    counters["evidence_count"] = len(evidence_rows)
    counters["unique_sources"] = await _opportunity_count(ctx)
    counters["registry_suppressed"] = len(ctx.registry_suppressed_ids)
    await _write_gate_counters(ctx, evidence_rows=evidence_rows, scored_at=scored_at, base=counters)
    record_funnel_observability(counters)


async def _write_gate_counters(
    ctx: _WorkerContext,
    *,
    evidence_rows: list[EvidenceRecord],
    scored_at: datetime,
    base: dict[str, int],
) -> None:
    client_ids: list[ClientRequestIdentity] = []
    for row in evidence_rows:
        if not row.is_qualified:
            continue
        if not is_within_quality_window(row.published_at, now=scored_at):
            continue
        if not is_client_request(
            category=row.detection_category,
            service_profiles=row.service_profiles,
            hard_exclusion=row.hard_exclusion,
        ):
            continue
        client_ids.append(
            ClientRequestIdentity(
                telegram_peer_id=row.source_telegram_id,
                telegram_message_id=row.telegram_message_id,
                normalized_hash=row.normalized_hash,
            )
        )
    global_distinct = distinct_client_request_count(client_ids)
    opp_rows = list(
        (
            await ctx.session.execute(
                select(SourceOpportunitySnapshot).where(
                    SourceOpportunitySnapshot.run_id == ctx.run.id
                )
            )
        ).scalars()
    )
    gate = evaluate_run_gate(
        truth_statuses=tuple(o.truth_status for o in opp_rows),  # type: ignore[arg-type]
        globally_distinct_client_requests=global_distinct,
        hit_run_cap=bool(base.get("hit_run_cap"))
        or int(base.get("history_scanned_total", 0)) >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN,
        pool_exhausted=bool(base.get("pool_exhausted")),
    )
    raw = {**base}
    raw["quality_sources"] = gate.quality_sources
    raw["near_sources"] = gate.near_sources
    raw["inconclusive_sources"] = gate.inconclusive_sources
    raw["rejected_sources"] = gate.rejected_sources
    raw["globally_distinct_client_requests"] = global_distinct
    raw["gate_status"] = gate.gate_status
    if (
        raw.get("hit_run_cap")
        or int(raw.get("history_scanned_total", 0)) >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
    ):
        raw["hit_run_cap"] = 1
    ctx.run.counters_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
