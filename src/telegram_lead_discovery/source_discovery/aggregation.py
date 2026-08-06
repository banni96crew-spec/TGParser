"""Pure aggregation and replacement acquisition for keyword discovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.detection.engine import seed_catalog_detect
from telegram_lead_discovery.source_discovery.evidence import (
    MAX_EVIDENCE_PER_RUN,
    MAX_QUALIFIED_EVIDENCE_PER_RUN,
    AnnotatedSearchHit,
    DetectFn,
    EvidenceRecord,
    evidence_from_hit,
    is_within_evidence_window,
    merge_evidence_duplicates,
)
from telegram_lead_discovery.source_discovery.identity import (
    DismissedKeywordSourceIndex,
    PresentedKeywordSourceIndex,
    ResolvedSourceIdentity,
    SourceRegistryIndex,
    is_registry_suppressed,
    resolve_dismissed_identity,
    resolve_presented_identity,
    resolve_source_identity,
)
from telegram_lead_discovery.source_discovery.opportunities import (
    OpportunitySnapshotRecord,
    build_opportunity_from_evidence,
)
from telegram_lead_discovery.source_discovery.opportunity_score import (
    opportunity_sort_key,
    sort_opportunities,
)


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """Aggregated evidence + opportunity snapshots for one run fragment."""

    evidence: tuple[EvidenceRecord, ...]
    opportunities: tuple[OpportunitySnapshotRecord, ...]
    budget_skipped_count: int
    window_skipped_count: int
    registry_suppressed_ids: frozenset[int] = frozenset()
    dismissed_suppressed_ids: frozenset[int] = frozenset()
    presented_suppressed_ids: frozenset[int] = frozenset()


def aggregate_search_hits(
    annotated_hits: Sequence[AnnotatedSearchHit],
    *,
    run_id: int,
    scored_at: datetime,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
    presented: PresentedKeywordSourceIndex | None = None,
    detect_fn: DetectFn = seed_catalog_detect,
    evidence_cap: int = MAX_EVIDENCE_PER_RUN,
    existing_evidence_count: int = 0,
    linked_parents: Mapping[int, int] | None = None,
) -> AggregationResult:
    """Compatibility entry point with the stable public signature."""
    return _aggregate_search_hits_with_budget(
        annotated_hits,
        run_id=run_id,
        scored_at=scored_at,
        registry=registry,
        dismissed=dismissed,
        presented=presented,
        detect_fn=detect_fn,
        evidence_cap=evidence_cap,
        existing_evidence_count=existing_evidence_count,
        linked_parents=linked_parents,
    )


def _aggregate_search_hits_with_budget(
    annotated_hits: Sequence[AnnotatedSearchHit],
    *,
    run_id: int,
    scored_at: datetime,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
    presented: PresentedKeywordSourceIndex | None = None,
    detect_fn: DetectFn = seed_catalog_detect,
    evidence_cap: int = MAX_EVIDENCE_PER_RUN,
    qualified_evidence_cap: int = MAX_QUALIFIED_EVIDENCE_PER_RUN,
    existing_evidence_count: int = 0,
    existing_qualified_evidence_count: int = 0,
    linked_parents: Mapping[int, int] | None = None,
) -> AggregationResult:
    """Aggregate hits → evidence + opportunity snapshots (phases E/H/I).

    Isolation: returns in-memory drafts only. Caller (worker) persists.
    Never creates TelegramMessage, Lead, outbox, or checkpoint rows.
    """
    window_skipped = 0
    drafts: list[EvidenceRecord] = []
    source_meta: dict[int, SourceSnapshot] = {}
    identities: dict[int, ResolvedSourceIdentity] = {}
    suppressed_ids: set[int] = set()
    dismissed_ids: set[int] = set()
    presented_ids: set[int] = set()

    for annotated in annotated_hits:
        hit = annotated.hit
        if not is_within_evidence_window(hit.published_at, now=scored_at):
            window_skipped += 1
            continue
        identity = resolve_source_identity(
            telegram_id=hit.source.telegram_id,
            username=hit.source.username,
            registry=registry,
        )
        if is_registry_suppressed(identity, registry=registry):
            suppressed_ids.add(identity.canonical_telegram_id)
            continue
        dismissed_match = resolve_dismissed_identity(
            telegram_id=identity.canonical_telegram_id,
            username=identity.username_normalized or hit.source.username,
            dismissed=dismissed,
        )
        if dismissed_match is not None:
            dismissed_ids.add(dismissed_match.canonical_telegram_id)
            continue
        presented_match = resolve_presented_identity(
            telegram_id=identity.canonical_telegram_id,
            username=identity.username_normalized or hit.source.username,
            presented=presented,
        )
        if presented_match is not None:
            presented_ids.add(presented_match.canonical_telegram_id)
            continue
        identities[identity.canonical_telegram_id] = identity
        # Remap snapshot telegram_id to canonical for grouping.
        canon_source = SourceSnapshot(
            schema_version=hit.source.schema_version,
            telegram_id=identity.canonical_telegram_id,
            username=identity.username_normalized or hit.source.username,
            title=hit.source.title,
            source_type=hit.source.source_type,
            public_url=hit.source.public_url,
            accessible=hit.source.accessible,
        )
        source_meta[identity.canonical_telegram_id] = canon_source
        drafts.append(
            evidence_from_hit(
                annotated,
                run_id=run_id,
                identity=identity,
                detect_fn=detect_fn,
            )
        )

    merged = merge_evidence_duplicates(drafts)
    # Stable order: published_at ASC, then telegram ids for budget determinism.
    merged.sort(
        key=lambda e: (
            e.published_at,
            e.source_telegram_id,
            e.telegram_message_id,
        )
    )

    remaining = max(0, evidence_cap - existing_evidence_count)
    qualified_remaining = max(0, qualified_evidence_cap - existing_qualified_evidence_count)
    kept: list[EvidenceRecord] = []
    budget_skipped = 0
    for record in merged:
        if len(kept) >= remaining:
            budget_skipped += 1
            continue
        if record.is_qualified:
            if qualified_remaining <= 0:
                budget_skipped += 1
                continue
            qualified_remaining -= 1
        kept.append(record)

    by_source: dict[int, list[EvidenceRecord]] = {}
    for row in kept:
        by_source.setdefault(row.source_telegram_id, []).append(row)

    parents = linked_parents or {}
    opportunities: list[OpportunitySnapshotRecord] = []
    for telegram_id, rows in by_source.items():
        snap = source_meta[telegram_id]
        identity = identities[telegram_id]
        opportunities.append(
            build_opportunity_from_evidence(
                run_id=run_id,
                source=snap,
                evidence=rows,
                scored_at=scored_at,
                registry_source_id=identity.registry_source_id,
                linked_parent_telegram_id=parents.get(telegram_id),
            )
        )

    opportunities.sort(key=lambda o: opportunity_sort_key(o.rank_key()))
    return AggregationResult(
        evidence=tuple(kept),
        opportunities=tuple(opportunities),
        budget_skipped_count=budget_skipped,
        window_skipped_count=window_skipped,
        registry_suppressed_ids=frozenset(suppressed_ids),
        dismissed_suppressed_ids=frozenset(dismissed_ids),
        presented_suppressed_ids=frozenset(presented_ids),
    )


def sort_opportunity_snapshots(
    snapshots: Sequence[OpportunitySnapshotRecord],
) -> list[OpportunitySnapshotRecord]:
    keys = [s.rank_key() for s in snapshots]
    ordered_keys = sort_opportunities(keys)
    by_id = {s.source_telegram_id: s for s in snapshots}
    return [by_id[k.telegram_id] for k in ordered_keys]


@dataclass(frozen=True, slots=True)
class ReplacementAcquisitionResult:
    """Result of cursor/replacement acquisition after suppress (SRC-040)."""

    acquired_total: int
    suppressed_total: int
    qualified_candidate_ids: list[int]
    replacement_fetches_total: int
    pool_exhausted: bool
    pool_exhausted_reason: str | None = None
    canonicalized_total: int = 0


def acquire_with_replacement(
    pages: Sequence[Sequence[int]],
    *,
    is_suppressed: Callable[[int], bool],
    target_quota: int,
    provider_exhausted: bool = False,
) -> ReplacementAcquisitionResult:
    """Consume pages; claim exhaustion only when the provider proves it."""
    acquired = 0
    suppressed = 0
    qualified: list[int] = []
    seen: set[int] = set()
    for page in pages:
        for tid in page:
            if tid in seen:
                continue
            seen.add(tid)
            acquired += 1
            if is_suppressed(tid):
                suppressed += 1
                continue
            qualified.append(tid)
    first_page_kept = 0
    if pages:
        for tid in pages[0]:
            if tid not in seen:
                continue
            if not is_suppressed(tid):
                first_page_kept += 1
        # Recount unique non-suppressed from first page only.
        first_seen: set[int] = set()
        first_page_kept = 0
        for tid in pages[0]:
            if tid in first_seen:
                continue
            first_seen.add(tid)
            if not is_suppressed(tid):
                first_page_kept += 1
    replacement_fetches = 0
    if len(pages) > 1 and first_page_kept < target_quota:
        replacement_fetches = len(pages) - 1
    pool_exhausted = provider_exhausted and len(qualified) < target_quota
    reason: str | None = None
    if pool_exhausted:
        if acquired == 0:
            reason = "provider_empty"
        else:
            reason = "no_unseen_after_suppress"
    return ReplacementAcquisitionResult(
        acquired_total=acquired,
        suppressed_total=suppressed,
        qualified_candidate_ids=qualified,
        replacement_fetches_total=replacement_fetches,
        pool_exhausted=pool_exhausted,
        pool_exhausted_reason=reason,
        canonicalized_total=acquired,
    )


__all__ = [
    "AggregationResult",
    "ReplacementAcquisitionResult",
    "acquire_with_replacement",
    "aggregate_search_hits",
    "sort_opportunity_snapshots",
]
