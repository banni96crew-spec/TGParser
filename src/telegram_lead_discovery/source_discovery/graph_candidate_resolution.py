"""Resolve username-only graph candidates before database writes."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.collector.ports import (
    GatewayPermanentError,
    GatewaySourceInaccessible,
    GraphEdgeDTO,
    PublicSourceRef,
    SourceRef,
)
from telegram_lead_discovery.source_discovery.graph_cursor import (
    snapshot_from_dict,
    snapshot_to_dict,
)
from telegram_lead_discovery.source_discovery.graph_discovery import (
    GraphCandidateResult,
    GraphQueueItem,
    plan_edge_outcome,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_state import (
    _save_graph_cursor,
)


async def resolve_planned_candidate(
    ctx: Any,
    node: GraphQueueItem,
    edge: GraphEdgeDTO,
    planned: GraphCandidateResult,
) -> tuple[Any | None, GraphCandidateResult]:
    """Resolve one candidate without leaving an open write transaction."""
    username = planned.normalized_reference.casefold()
    cached = ctx.resolved_sources.get(f"username:{username}")
    if cached is not None:
        snapshot = snapshot_from_dict(cached)
    elif ctx.budget.remaining_resolves() <= 0:
        ctx.budget.budget_skipped_total += 1
        return None, _as_outcome(planned, "budget_skipped")
    else:
        try:
            ref = SourceRef(schema_version=1, source_id=0, username=username)
            resolver = getattr(ctx.gateway, "resolve_graph_source", None)
            if resolver is not None:
                snapshot = await resolver(ref)
            else:
                snapshot = await ctx.gateway.resolve_public_source(
                    PublicSourceRef(schema_version=1, username_or_url=username)
                )
        except (GatewaySourceInaccessible, GatewayPermanentError):
            ctx.budget.unsupported_total += 1
            return None, _as_outcome(planned, "unsupported_source")
        ctx.budget.resolves_used += 1
        packed = snapshot_to_dict(snapshot)
        ctx.resolved_sources[f"username:{username}"] = packed
        ctx.resolved_sources[f"peer:{snapshot.telegram_id}"] = packed
        _save_graph_cursor(ctx)
        await ctx.session.commit()

    resolved_edge = GraphEdgeDTO(
        schema_version=1,
        edge_type=edge.edge_type,
        seed_telegram_id=edge.seed_telegram_id,
        raw_reference=edge.raw_reference,
        normalized_username=snapshot.username.casefold(),
        target=snapshot,
        evidence_message_id=edge.evidence_message_id,
    )
    ctx.budget.resolved_canonical_keys.discard(f"username:{username}")
    replanned = plan_edge_outcome(
        resolved_edge,
        child_depth=node.depth + 1,
        budget=ctx.budget,
        registry=ctx.registry,
        dismissed=ctx.dismissed,
    )
    return snapshot, replanned


def _as_outcome(planned: GraphCandidateResult, outcome: str) -> GraphCandidateResult:
    values = {
        field: getattr(planned, field)
        for field in planned.__dataclass_fields__
    }
    values["outcome"] = outcome
    return GraphCandidateResult(**values)


__all__ = ["resolve_planned_candidate"]
