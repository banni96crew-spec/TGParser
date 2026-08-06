from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _loads_counters,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _load_evidence_records,
)


async def _terminal_opportunities(ctx: _WorkerContext) -> list[SourceOpportunitySnapshot]:
    return list(
        (
            await ctx.session.execute(
                select(SourceOpportunitySnapshot).where(
                    SourceOpportunitySnapshot.run_id == ctx.run.id,
                    SourceOpportunitySnapshot.qualification_version
                    == "active-client-chat-v1",
                )
            )
        ).scalars()
    )


async def _phase_finalize_opportunities(ctx: _WorkerContext) -> None:
    """Publish only terminal ActiveClientChat v1 snapshots and gate truth."""
    ctx.run.phase = "I"
    await ctx.session.flush()
    evidence_rows = await _load_evidence_records(ctx)
    opportunities = await _terminal_opportunities(ctx)

    qualified_evidence = sum(1 for row in evidence_rows if row.is_qualified)
    record_qualified_evidence(qualified_evidence)
    for opportunity in opportunities:
        record_score(band=opportunity.band)

    unique_evidence_sources = {row.source_telegram_id for row in evidence_rows}
    presented = len(opportunities)
    counters = merge_funnel_counters(
        _loads_counters(ctx.run.counters_json),
        canonicalized_total=len(unique_evidence_sources),
        dismissed_suppressed=len(ctx.dismissed_suppressed_ids),
        presented_suppressed=len(ctx.presented_suppressed_ids),
        cooldown_suppressed=len(ctx.presented_suppressed_ids),
        qualified_total=sum(1 for row in opportunities if row.client_request_count > 0),
        presented_total=presented,
        novel_presented_total=presented,
    )
    counters["evidence_count"] = len(evidence_rows)
    counters["unique_sources"] = presented
    counters["registry_suppressed"] = len(ctx.registry_suppressed_ids)
    await _write_gate_counters(ctx, opportunities=opportunities, base=counters)
    record_funnel_observability(counters)


async def _write_gate_counters(
    ctx: _WorkerContext,
    *,
    opportunities: list[SourceOpportunitySnapshot],
    base: dict[str, Any],
) -> None:
    pool_exhausted = bool(ctx.run.pool_exhausted or base.get("pool_exhausted"))
    hit_run_cap = bool(base.get("hit_run_cap")) or int(
        base.get("history_scanned_total", 0)
    ) >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
    gate = evaluate_run_gate(
        truth_statuses=tuple(row.truth_status for row in opportunities),  # type: ignore[arg-type]
        globally_distinct_client_requests=sum(
            row.client_request_count for row in opportunities
        ),
        hit_run_cap=hit_run_cap,
        pool_exhausted=pool_exhausted,
    )
    raw = {**base}
    raw.update(
        {
            "quality_sources": gate.quality_sources,
            "near_sources": gate.near_sources,
            "inconclusive_sources": gate.inconclusive_sources,
            "rejected_sources": gate.rejected_sources,
            "countable_client_requests": sum(
                row.client_request_count for row in opportunities
            ),
            "distinct_client_authors": sum(
                row.client_request_author_count for row in opportunities
            ),
            "gate_status": gate.gate_status,
            "hit_run_cap": int(hit_run_cap),
            "pool_exhausted": int(pool_exhausted),
        }
    )
    ctx.run.gate_status = gate.gate_status
    ctx.run.pool_exhausted = pool_exhausted
    base.update(raw)
    ctx.run.counters_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
