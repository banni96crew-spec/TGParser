"""Stateful graph-discovery orchestration."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GraphEdgeDTO,
    SourceRef,
    SourceSnapshot,
    TelegramGateway,
)
from telegram_lead_discovery.source_discovery.graph_policy import (
    GRAPH_MESSAGE_SAMPLE_LIMIT,
    MAX_GRAPH_DEPTH,
    MAX_OUTGOING_EDGES_PER_SEED,
    MAX_UNIQUE_GRAPH_CANDIDATES,
    GraphBudget,
    GraphCandidateResult,
    GraphQueueItem,
    filter_allowed_public_edges,
    truncate_outgoing_edges,
)
from telegram_lead_discovery.source_discovery.graph_repository import (
    _find_existing_source,
    find_active_graph_run,
)
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    Job,
    SourceDiscoveryEvent,
    TelegramSource,
)

JOB_TYPE_GRAPH_DISCOVERY = "discovery"
TERMINAL_GRAPH_RUN_STATES = frozenset({"succeeded", "failed", "cancelled"})


class GraphRunStartError(ValueError):
    """Raised when StartGraphDiscoveryRun is rejected."""


@dataclass(frozen=True, slots=True)
class StartGraphDiscoveryResult:
    run: DiscoveryRun
    job: Job
    seed_count: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def start_graph_discovery_run(
    session: AsyncSession,
    *,
    seed_source_ids: Sequence[int],
) -> StartGraphDiscoveryResult:
    """Create DiscoveryRun(run_type=graph) + Job(discovery) atomically."""
    seeds = [int(s) for s in seed_source_ids]
    if not seeds:
        raise GraphRunStartError("seeds_required")
    if await find_active_graph_run(session) is not None:
        raise GraphRunStartError("active_graph_run_exists")

    for source_id in seeds:
        row = await session.get(TelegramSource, source_id)
        if row is None:
            raise GraphRunStartError(f"seed_not_found:{source_id}")
        if row.telegram_id is None:
            raise GraphRunStartError(f"seed_unresolved:{source_id}")

    now = _utcnow()
    run = DiscoveryRun(
        run_type="graph",
        root_source_ids_json=json.dumps(seeds, ensure_ascii=False),
        max_depth=MAX_GRAPH_DEPTH,
        expansion_cap=MAX_OUTGOING_EDGES_PER_SEED,
        candidate_cap=MAX_UNIQUE_GRAPH_CANDIDATES,
        state="queued",
        phase="expand",
        counters_json="{}",
        created_at=now,
    )
    session.add(run)
    await session.flush()

    job = await enqueue_job(
        session,
        job_type=JOB_TYPE_GRAPH_DISCOVERY,
        payload={"run_id": run.id, "schema_version": 1},
        dedupe_key=f"graph-discovery:{run.id}",
    )
    return StartGraphDiscoveryResult(run=run, job=job, seed_count=len(seeds))


async def collect_edges_for_seed(
    gateway: TelegramGateway,
    *,
    seed: GraphQueueItem,
    outgoing_cap: int = MAX_OUTGOING_EDGES_PER_SEED,
    sample_limit: int = GRAPH_MESSAGE_SAMPLE_LIMIT,
) -> list[GraphEdgeDTO]:
    """Fetch allowed public edges for one seed (recommendations + linked + sample)."""
    ref = SourceRef(
        schema_version=1,
        source_id=seed.seed_source_id or 0,
        telegram_id=seed.seed_telegram_id,
        username=seed.username,
    )
    edges: list[GraphEdgeDTO] = []

    recommendations = await gateway.get_recommendations(ref, outgoing_cap)
    for snap in recommendations:
        edges.append(
            GraphEdgeDTO(
                schema_version=1,
                edge_type="recommendation",
                seed_telegram_id=seed.seed_telegram_id,
                raw_reference=f"@{snap.username}",
                normalized_username=snap.username.lower(),
                target=snap,
            )
        )

    linked = await gateway.get_linked_discussion(ref)
    if linked is not None and linked.username:
        edges.append(
            GraphEdgeDTO(
                schema_version=1,
                edge_type="linked_discussion",
                seed_telegram_id=seed.seed_telegram_id,
                raw_reference=f"@{linked.username}",
                normalized_username=linked.username.lower(),
                target=linked,
            )
        )

    from telegram_lead_discovery.collector.ports import GraphSampleRequest

    sampled = await gateway.sample_public_graph_edges(
        GraphSampleRequest(
            schema_version=1,
            source=ref,
            message_limit=sample_limit,
        )
    )
    edges.extend(sampled)

    public = filter_allowed_public_edges(edges)
    return list(truncate_outgoing_edges(public, limit=outgoing_cap))


async def persist_graph_candidate(
    session: AsyncSession,
    *,
    run: DiscoveryRun,
    result: GraphCandidateResult,
    parent_source_id: int | None,
    budget: GraphBudget,
    snapshot: SourceSnapshot | None = None,
) -> TelegramSource | None:
    """Persist SourceDiscoveryEvent and maybe create TelegramSource(candidate)."""
    snap = snapshot if snapshot is not None else result.snapshot
    source: TelegramSource | None = None
    outcome = result.outcome

    if outcome in {"candidate", "merged"} and snap is not None:
        existing = await _find_existing_source(session, snap)
        if existing is not None:
            source = existing
            outcome = "merged"
            if result.outcome == "candidate":
                budget.merged_total += 1
        elif outcome == "candidate":
            source = TelegramSource(
                telegram_id=snap.telegram_id,
                username_normalized=snap.username.lower(),
                title=snap.title,
                source_type=snap.source_type,
                public_url=snap.public_url,
                lifecycle_state="candidate",
                quality_score=2,
            )
            session.add(source)
            await session.flush()
            budget.candidates_created += 1
        elif result.source_id is not None:
            source = await session.get(TelegramSource, result.source_id)

    session.add(
        SourceDiscoveryEvent(
            event_id=str(uuid.uuid4()),
            run_id=run.id,
            source_id=source.id if source is not None else None,
            method=result.method,
            parent_source_id=parent_source_id,
            evidence_message_id=result.evidence_message_id,
            raw_reference=result.raw_reference,
            normalized_reference=result.normalized_reference or "",
            outcome=outcome,
            depth=result.depth,
            discovered_at=_utcnow(),
        )
    )
    await session.flush()
    return source
