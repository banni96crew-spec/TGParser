"""Bounded public-only graph discovery (SRC-003..016, SRC-042, D-017).

Pure budget/edge helpers plus transactional graph-run start. Worker expansion
lives in ``worker.py`` so keyword Wave 03 phases stay untouched.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GraphEdgeDTO,
    SourceRef,
    SourceSnapshot,
    TelegramGateway,
)
from telegram_lead_discovery.source_discovery import graph_policy as _graph_policy
from telegram_lead_discovery.source_discovery.identity import (
    RegistrySourceEntry,
    SourceRegistryIndex,
)
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    Job,
    SourceAlias,
    SourceDiscoveryEvent,
    TelegramSource,
)

ALLOWED_GRAPH_EDGE_TYPES = _graph_policy.ALLOWED_GRAPH_EDGE_TYPES
GRAPH_MESSAGE_SAMPLE_LIMIT = _graph_policy.GRAPH_MESSAGE_SAMPLE_LIMIT
MAX_GRAPH_DEPTH = _graph_policy.MAX_GRAPH_DEPTH
MAX_OUTGOING_EDGES_PER_SEED = _graph_policy.MAX_OUTGOING_EDGES_PER_SEED
MAX_RESOLVE_OPS = _graph_policy.MAX_RESOLVE_OPS
MAX_UNIQUE_GRAPH_CANDIDATES = _graph_policy.MAX_UNIQUE_GRAPH_CANDIDATES
GraphBudget = _graph_policy.GraphBudget
GraphCandidateResult = _graph_policy.GraphCandidateResult
GraphOutcome = _graph_policy.GraphOutcome
GraphQueueItem = _graph_policy.GraphQueueItem
canonical_key_for_snapshot = _graph_policy.canonical_key_for_snapshot
canonical_key_for_username = _graph_policy.canonical_key_for_username
extract_public_usernames_from_text = _graph_policy.extract_public_usernames_from_text
filter_allowed_public_edges = _graph_policy.filter_allowed_public_edges
is_private_invite_ref = _graph_policy.is_private_invite_ref
plan_edge_outcome = _graph_policy.plan_edge_outcome
truncate_outgoing_edges = _graph_policy.truncate_outgoing_edges

JOB_TYPE_GRAPH_DISCOVERY = "discovery"
ACTIVE_GRAPH_RUN_STATES = frozenset({"queued", "running"})
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


async def find_active_graph_run(session: AsyncSession) -> DiscoveryRun | None:
    result = await session.execute(
        select(DiscoveryRun)
        .where(
            DiscoveryRun.run_type == "graph",
            DiscoveryRun.state.in_(tuple(ACTIVE_GRAPH_RUN_STATES)),
        )
        .order_by(DiscoveryRun.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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


async def load_graph_seeds(
    session: AsyncSession, run: DiscoveryRun
) -> list[GraphQueueItem]:
    raw = json.loads(run.root_source_ids_json or "[]")
    if not isinstance(raw, list):
        return []
    items: list[GraphQueueItem] = []
    for source_id in raw:
        row = await session.get(TelegramSource, int(source_id))
        if row is None or row.telegram_id is None:
            continue
        items.append(
            GraphQueueItem(
                seed_telegram_id=int(row.telegram_id),
                seed_source_id=row.id,
                depth=0,
                username=row.username_normalized,
            )
        )
    # SRC-006: depth ASC, discovered_at ASC, normalized reference ASC.
    items.sort(key=lambda i: (i.depth, i.seed_telegram_id, i.username or ""))
    return items


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


async def _find_existing_source(
    session: AsyncSession, snap: SourceSnapshot
) -> TelegramSource | None:
    by_id = await session.execute(
        select(TelegramSource).where(TelegramSource.telegram_id == snap.telegram_id)
    )
    found = by_id.scalar_one_or_none()
    if found is not None:
        return found
    username = snap.username.lower()
    by_user = await session.execute(
        select(TelegramSource).where(TelegramSource.username_normalized == username)
    )
    found = by_user.scalar_one_or_none()
    if found is not None:
        return found
    alias = await session.execute(
        select(SourceAlias).where(SourceAlias.normalized_username == username)
    )
    alias_row = alias.scalar_one_or_none()
    if alias_row is not None:
        return await session.get(TelegramSource, alias_row.source_id)
    return None


async def load_registry_index(session: AsyncSession) -> SourceRegistryIndex:
    rows = list((await session.execute(select(TelegramSource))).scalars().all())
    aliases = list((await session.execute(select(SourceAlias))).scalars().all())
    alias_by_source: dict[int, list[str]] = {}
    for alias in aliases:
        alias_by_source.setdefault(alias.source_id, []).append(alias.normalized_username)
    entries = [
        RegistrySourceEntry(
            source_id=row.id,
            telegram_id=row.telegram_id,
            username_normalized=row.username_normalized,
            aliases=tuple(alias_by_source.get(row.id, ())),
        )
        for row in rows
    ]
    return SourceRegistryIndex.from_entries(entries)
