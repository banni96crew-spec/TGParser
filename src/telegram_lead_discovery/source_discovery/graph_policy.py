"""Pure graph discovery parsing, identity, and budget policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from telegram_lead_discovery.collector.ports import GraphEdgeDTO, GraphEdgeType, SourceSnapshot
from telegram_lead_discovery.source_discovery.graph_edges import (
    ALLOWED_GRAPH_EDGE_TYPES,
    extract_public_usernames_from_text,
    filter_allowed_public_edges,
    is_private_invite_ref,
    truncate_outgoing_edges,
)
from telegram_lead_discovery.source_discovery.identity import (
    DismissedKeywordSourceIndex,
    SourceRegistryIndex,
    is_registry_suppressed,
    resolve_dismissed_identity,
    resolve_source_identity,
)
from telegram_lead_discovery.source_discovery.normalize import normalize_source_ref

# D-017 / SRC-004 / SRC-005 / SRC-042 — plan Wave 04 depth=1 is superseded.
MAX_GRAPH_DEPTH = 2
MAX_OUTGOING_EDGES_PER_SEED = 25
MAX_UNIQUE_GRAPH_CANDIDATES = 100
MAX_RESOLVE_OPS = 25
GRAPH_MESSAGE_SAMPLE_LIMIT = 100

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


@dataclass(frozen=True, slots=True)
class GraphQueueItem:
    """BFS expansion node (SRC-006)."""

    seed_telegram_id: int
    seed_source_id: int | None
    depth: int
    username: str | None = None
    access_hash: int | None = None


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
