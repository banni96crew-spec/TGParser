"""Bounded public-only graph discovery (SRC-003..016, SRC-042, D-017).

Pure budget/edge helpers plus transactional graph-run start. Worker expansion
lives in ``worker.py`` so keyword Wave 03 phases stay untouched.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import regex
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GraphEdgeDTO,
    GraphEdgeType,
    SourceRef,
    SourceSnapshot,
    TelegramGateway,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    DismissedKeywordSourceIndex,
    RegistrySourceEntry,
    SourceRegistryIndex,
    is_registry_suppressed,
    resolve_dismissed_identity,
    resolve_source_identity,
)
from telegram_lead_discovery.source_discovery.normalize import normalize_source_ref
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    Job,
    SourceAlias,
    SourceDiscoveryEvent,
    TelegramSource,
)

JOB_TYPE_GRAPH_DISCOVERY = "discovery"
ACTIVE_GRAPH_RUN_STATES = frozenset({"queued", "running"})
TERMINAL_GRAPH_RUN_STATES = frozenset({"succeeded", "failed", "cancelled"})

# D-017 / SRC-004 / SRC-005 / SRC-042 — plan Wave 04 depth=1 is superseded.
MAX_GRAPH_DEPTH = 2
MAX_OUTGOING_EDGES_PER_SEED = 25
MAX_UNIQUE_GRAPH_CANDIDATES = 100
MAX_RESOLVE_OPS = 25
GRAPH_MESSAGE_SAMPLE_LIMIT = 50

ALLOWED_GRAPH_EDGE_TYPES: frozenset[GraphEdgeType] = frozenset(
    {
        "recommendation",
        "public_link",
        "mention",
        "forward_origin",
        "linked_discussion",
    }
)

GraphOutcome = Literal[
    "candidate",
    "merged",
    "unsupported_source",
    "budget_skipped",
    "depth_skipped",
    "duplicate_in_run",
    "registry_suppressed",
    "dismissed_suppressed",
    "invalid_reference",
]

_MENTION_RE = regex.compile(r"(?<![a-zA-Z0-9_])@([a-zA-Z0-9_]{5,32})\b")
_TME_RE = regex.compile(
    r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32})(?:/[0-9]+)?(?:\?[^\s]*)?",
    flags=regex.IGNORECASE,
)
_PRIVATE_TME_PREFIXES = frozenset(
    {"joinchat", "addstickers", "share", "proxy", "socks", "c", "s"}
)
_REGEX_TIMEOUT = 0.05


class GraphRunStartError(ValueError):
    """Raised when StartGraphDiscoveryRun is rejected."""


@dataclass(frozen=True, slots=True)
class StartGraphDiscoveryResult:
    run: DiscoveryRun
    job: Job
    seed_count: int


@dataclass(frozen=True, slots=True)
class GraphQueueItem:
    """BFS expansion node (SRC-006)."""

    seed_telegram_id: int
    seed_source_id: int | None
    depth: int
    username: str | None = None


@dataclass(frozen=True, slots=True)
class GraphCandidateResult:
    outcome: GraphOutcome
    method: GraphEdgeType
    depth: int
    raw_reference: str
    normalized_reference: str
    parent_source_id: int | None
    seed_telegram_id: int
    snapshot: SourceSnapshot | None = None
    source_id: int | None = None
    evidence_message_id: int | None = None


@dataclass
class GraphBudget:
    max_depth: int = MAX_GRAPH_DEPTH
    max_outgoing_edges: int = MAX_OUTGOING_EDGES_PER_SEED
    candidate_cap: int = MAX_UNIQUE_GRAPH_CANDIDATES
    resolve_cap: int = MAX_RESOLVE_OPS
    resolves_used: int = 0
    candidates_created: int = 0
    merged_total: int = 0
    depth_skipped_total: int = 0
    budget_skipped_total: int = 0
    unsupported_total: int = 0
    invalid_total: int = 0
    duplicate_in_run_total: int = 0
    registry_suppressed_total: int = 0
    dismissed_suppressed_total: int = 0
    resolved_canonical_keys: set[str] = field(default_factory=set)

    def remaining_candidates(self) -> int:
        return max(0, self.candidate_cap - self.candidates_created)

    def remaining_resolves(self) -> int:
        return max(0, self.resolve_cap - self.resolves_used)

    def to_counters(self) -> dict[str, int]:
        return {
            "resolves": self.resolves_used,
            "created_candidates": self.candidates_created,
            "merged_candidates": self.merged_total,
            "depth_skipped_total": self.depth_skipped_total,
            "budget_skipped_total": self.budget_skipped_total,
            "unsupported_sources": self.unsupported_total,
            "invalid_references": self.invalid_total,
            "duplicate_in_run": self.duplicate_in_run_total,
            "registry_suppressed": self.registry_suppressed_total,
            "dismissed_suppressed": self.dismissed_suppressed_total,
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


def is_private_invite_ref(raw: str) -> bool:
    text = raw.strip().casefold()
    if "t.me/+" in text or "t.me/joinchat/" in text:
        return True
    if text.startswith("+") or text.startswith("joinchat/"):
        return True
    return False


def extract_public_usernames_from_text(text: str) -> tuple[tuple[str, GraphEdgeType], ...]:
    """Pure extractor for mention / public_link tokens (no private invites)."""
    if not text:
        return ()
    ordered: list[tuple[str, GraphEdgeType]] = []
    seen: set[str] = set()
    try:
        for match in _TME_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token in _PRIVATE_TME_PREFIXES or token.startswith("+"):
                continue
            if token not in seen:
                seen.add(token)
                ordered.append((token, "public_link"))
        for match in _MENTION_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token not in seen:
                seen.add(token)
                ordered.append((token, "mention"))
    except TimeoutError:
        return tuple(ordered)
    return tuple(ordered)


def truncate_outgoing_edges(
    edges: Sequence[GraphEdgeDTO], *, limit: int = MAX_OUTGOING_EDGES_PER_SEED
) -> tuple[GraphEdgeDTO, ...]:
    """Cap examined outgoing edges per seed (SRC-042)."""
    if limit < 0:
        return ()
    return tuple(edges[:limit])


def filter_allowed_public_edges(
    edges: Iterable[GraphEdgeDTO],
) -> tuple[GraphEdgeDTO, ...]:
    """Drop disallowed edge types and private/inaccessible pre-resolved targets."""
    kept: list[GraphEdgeDTO] = []
    for edge in edges:
        if edge.edge_type not in ALLOWED_GRAPH_EDGE_TYPES:
            continue
        if is_private_invite_ref(edge.raw_reference):
            continue
        target = edge.target
        if target is not None:
            if (
                not target.accessible
                or not target.username
                or target.source_type not in {"channel", "megagroup", "group"}
            ):
                continue
        kept.append(edge)
    return tuple(kept)


def canonical_key_for_snapshot(snap: SourceSnapshot) -> str:
    return f"peer:{int(snap.telegram_id)}"


def canonical_key_for_username(username: str) -> str:
    return f"username:{username.casefold()}"


def plan_edge_outcome(
    edge: GraphEdgeDTO,
    *,
    child_depth: int,
    budget: GraphBudget,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
) -> GraphCandidateResult:
    """Decide outcome for one edge without I/O (budgets / suppress / depth)."""
    method = edge.edge_type
    raw = edge.raw_reference
    parent_id = None
    if child_depth > budget.max_depth:
        budget.depth_skipped_total += 1
        return GraphCandidateResult(
            outcome="depth_skipped",
            method=method,
            depth=child_depth,
            raw_reference=raw,
            normalized_reference="",
            parent_source_id=parent_id,
            seed_telegram_id=edge.seed_telegram_id,
            evidence_message_id=edge.evidence_message_id,
        )

    if is_private_invite_ref(raw):
        budget.unsupported_total += 1
        return GraphCandidateResult(
            outcome="unsupported_source",
            method=method,
            depth=child_depth,
            raw_reference=raw,
            normalized_reference="",
            parent_source_id=parent_id,
            seed_telegram_id=edge.seed_telegram_id,
            evidence_message_id=edge.evidence_message_id,
        )

    username: str | None = edge.normalized_username
    if username is None and edge.target is not None and edge.target.username:
        username = edge.target.username.lower()
    if username is None:
        try:
            username = normalize_source_ref(raw)
        except ValueError:
            budget.invalid_total += 1
            return GraphCandidateResult(
                outcome="invalid_reference",
                method=method,
                depth=child_depth,
                raw_reference=raw,
                normalized_reference="",
                parent_source_id=parent_id,
                seed_telegram_id=edge.seed_telegram_id,
                evidence_message_id=edge.evidence_message_id,
            )

    username = username.lower()
    snap = edge.target
    if snap is not None:
        key = canonical_key_for_snapshot(snap)
    else:
        key = canonical_key_for_username(username)

    if key in budget.resolved_canonical_keys:
        budget.duplicate_in_run_total += 1
        return GraphCandidateResult(
            outcome="duplicate_in_run",
            method=method,
            depth=child_depth,
            raw_reference=raw,
            normalized_reference=username,
            parent_source_id=parent_id,
            seed_telegram_id=edge.seed_telegram_id,
            snapshot=snap,
            evidence_message_id=edge.evidence_message_id,
        )

    # Dismiss suppress (reuse Wave 02/03 ledger). Registry hits merge, not skip.
    if snap is not None:
        dismissed_match = resolve_dismissed_identity(
            telegram_id=snap.telegram_id,
            username=username,
            dismissed=dismissed,
        )
        if dismissed_match is not None:
            budget.dismissed_suppressed_total += 1
            budget.resolved_canonical_keys.add(key)
            return GraphCandidateResult(
                outcome="dismissed_suppressed",
                method=method,
                depth=child_depth,
                raw_reference=raw,
                normalized_reference=username,
                parent_source_id=parent_id,
                seed_telegram_id=edge.seed_telegram_id,
                snapshot=snap,
                evidence_message_id=edge.evidence_message_id,
            )
        identity = resolve_source_identity(
            telegram_id=snap.telegram_id,
            username=username,
            registry=registry,
        )
        if is_registry_suppressed(identity, registry=registry):
            budget.resolved_canonical_keys.add(key)
            budget.merged_total += 1
            return GraphCandidateResult(
                outcome="merged",
                method=method,
                depth=child_depth,
                raw_reference=raw,
                normalized_reference=username,
                parent_source_id=parent_id,
                seed_telegram_id=edge.seed_telegram_id,
                snapshot=snap,
                source_id=identity.registry_source_id,
                evidence_message_id=edge.evidence_message_id,
            )
    elif dismissed is not None and username:
        # Username-only dismiss match before resolve.
        by_user = dismissed.by_username.get(username) or dismissed.by_alias.get(username)
        if by_user is not None:
            budget.dismissed_suppressed_total += 1
            budget.resolved_canonical_keys.add(key)
            return GraphCandidateResult(
                outcome="dismissed_suppressed",
                method=method,
                depth=child_depth,
                raw_reference=raw,
                normalized_reference=username,
                parent_source_id=parent_id,
                seed_telegram_id=edge.seed_telegram_id,
                evidence_message_id=edge.evidence_message_id,
            )

    if budget.remaining_candidates() <= 0:
        budget.budget_skipped_total += 1
        return GraphCandidateResult(
            outcome="budget_skipped",
            method=method,
            depth=child_depth,
            raw_reference=raw,
            normalized_reference=username,
            parent_source_id=parent_id,
            seed_telegram_id=edge.seed_telegram_id,
            snapshot=snap,
            evidence_message_id=edge.evidence_message_id,
        )

    needs_resolve = snap is None
    if needs_resolve and budget.remaining_resolves() <= 0:
        budget.budget_skipped_total += 1
        return GraphCandidateResult(
            outcome="budget_skipped",
            method=method,
            depth=child_depth,
            raw_reference=raw,
            normalized_reference=username,
            parent_source_id=parent_id,
            seed_telegram_id=edge.seed_telegram_id,
            evidence_message_id=edge.evidence_message_id,
        )

    budget.resolved_canonical_keys.add(key)
    return GraphCandidateResult(
        outcome="candidate",
        method=method,
        depth=child_depth,
        raw_reference=raw,
        normalized_reference=username,
        parent_source_id=parent_id,
        seed_telegram_id=edge.seed_telegram_id,
        snapshot=snap,
        evidence_message_id=edge.evidence_message_id,
    )


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
