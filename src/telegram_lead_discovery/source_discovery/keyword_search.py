"""Keyword scouting evidence aggregation and opportunity snapshots (SRC-021..025).

Pure domain API for Wave 4 step-09. Does NOT persist rows, call Telegram, or
create TelegramMessage / Lead / outbox / checkpoint (D-052).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from telegram_lead_discovery.collector.ports import SearchMessageHitDTO, SourceSnapshot
from telegram_lead_discovery.detection.engine import DetectionResult, detect
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    truncate_evidence_excerpt,
)
from telegram_lead_discovery.source_discovery.opportunity_score import (
    OpportunityBand,
    OpportunityRankKey,
    OpportunityScoreResult,
    opportunity_sort_key,
    score_opportunity,
    sort_opportunities,
)
from telegram_lead_discovery.source_discovery.service import normalize_username

DiscoveryChannel = Literal[
    "global_message",
    "directory",
    "public_posts",
    "source_verification",
    "linked_discussion",
]

MAX_EVIDENCE_PER_RUN = 500
MAX_DEEP_VERIFICATION_SOURCES = 25
MAX_MESSAGES_PER_SOURCE = 20
EVIDENCE_WINDOW_DAYS = 30
ECOMMERCE_SERVICE_CODE = "ecommerce"

DetectFn = Callable[[str], DetectionResult]


@dataclass(frozen=True, slots=True)
class RegistrySourceEntry:
    """Minimal registry view for SRC-022 identity resolution."""

    source_id: int
    telegram_id: int | None
    username_normalized: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceRegistryIndex:
    """Lookup indexes for identity order telegram_id → username → alias."""

    by_telegram_id: Mapping[int, RegistrySourceEntry] = field(default_factory=dict)
    by_username: Mapping[str, RegistrySourceEntry] = field(default_factory=dict)
    by_alias: Mapping[str, RegistrySourceEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: Sequence[RegistrySourceEntry]) -> SourceRegistryIndex:
        by_tid: dict[int, RegistrySourceEntry] = {}
        by_user: dict[str, RegistrySourceEntry] = {}
        by_alias: dict[str, RegistrySourceEntry] = {}
        for entry in entries:
            if entry.telegram_id is not None:
                by_tid[entry.telegram_id] = entry
            if entry.username_normalized:
                by_user[entry.username_normalized] = entry
            for alias in entry.aliases:
                by_alias[alias] = entry
        return cls(by_telegram_id=by_tid, by_username=by_user, by_alias=by_alias)


@dataclass(frozen=True, slots=True)
class DismissedKeywordSourceEntry:
    """Durable suppress row for future keyword runs (SRC-032)."""

    telegram_id: int
    username_normalized: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DismissedKeywordSourceIndex:
    """Lookup indexes for dismissed suppress identity matching."""

    by_telegram_id: Mapping[int, DismissedKeywordSourceEntry] = field(default_factory=dict)
    by_username: Mapping[str, DismissedKeywordSourceEntry] = field(default_factory=dict)
    by_alias: Mapping[str, DismissedKeywordSourceEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(
        cls, entries: Sequence[DismissedKeywordSourceEntry]
    ) -> DismissedKeywordSourceIndex:
        by_tid: dict[int, DismissedKeywordSourceEntry] = {}
        by_user: dict[str, DismissedKeywordSourceEntry] = {}
        by_alias: dict[str, DismissedKeywordSourceEntry] = {}
        for entry in entries:
            by_tid[entry.telegram_id] = entry
            if entry.username_normalized:
                by_user[entry.username_normalized] = entry
            for alias in entry.aliases:
                by_alias[alias] = entry
        return cls(by_telegram_id=by_tid, by_username=by_user, by_alias=by_alias)


@dataclass(frozen=True, slots=True)
class ResolvedSourceIdentity:
    """Canonical source identity after SRC-022 resolution."""

    canonical_telegram_id: int
    registry_source_id: int | None
    username_normalized: str | None
    matched_via: Literal[
        "telegram_id",
        "registry_telegram_id",
        "username",
        "alias",
        "username_fallback",
    ]


@dataclass(frozen=True, slots=True)
class DismissedIdentityMatch:
    canonical_telegram_id: int
    username_normalized: str | None
    matched_via: Literal["dismissed_telegram_id", "username", "alias"]


def registry_telegram_ids(registry: SourceRegistryIndex) -> frozenset[int]:
    """All telegram_id values currently present in the Source Registry index."""
    return frozenset(registry.by_telegram_id.keys())


def dismissed_telegram_ids(index: DismissedKeywordSourceIndex) -> frozenset[int]:
    """All telegram_id values currently suppressed by past dismiss actions."""
    return frozenset(index.by_telegram_id.keys())


def is_registry_suppressed(
    identity: ResolvedSourceIdentity,
    *,
    registry: SourceRegistryIndex | None = None,
) -> bool:
    """SRC-031 / D-059: true when identity already resolves to a registry source."""
    if identity.registry_source_id is not None:
        return True
    if registry is None:
        return False
    return identity.canonical_telegram_id in registry.by_telegram_id


def resolve_dismissed_identity(
    *,
    telegram_id: int,
    username: str | None,
    dismissed: DismissedKeywordSourceIndex | None = None,
) -> DismissedIdentityMatch | None:
    """Resolve whether a source matches the durable dismissed suppress set."""
    if dismissed is None:
        return None
    username_normalized: str | None = None
    if username:
        try:
            username_normalized = normalize_username(username)
        except ValueError:
            username_normalized = username.strip().lstrip("@").lower() or None

    by_tid = dismissed.by_telegram_id.get(telegram_id)
    if by_tid is not None:
        return DismissedIdentityMatch(
            canonical_telegram_id=by_tid.telegram_id,
            username_normalized=username_normalized or by_tid.username_normalized,
            matched_via="dismissed_telegram_id",
        )
    if username_normalized:
        by_user = dismissed.by_username.get(username_normalized)
        if by_user is not None:
            return DismissedIdentityMatch(
                canonical_telegram_id=by_user.telegram_id,
                username_normalized=username_normalized,
                matched_via="username",
            )
        by_alias = dismissed.by_alias.get(username_normalized)
        if by_alias is not None:
            return DismissedIdentityMatch(
                canonical_telegram_id=by_alias.telegram_id,
                username_normalized=username_normalized,
                matched_via="alias",
            )
    return None


@dataclass(frozen=True, slots=True)
class AnnotatedSearchHit:
    """Search hit annotated with run query ordinal and discovery channel."""

    hit: SearchMessageHitDTO
    query_ordinal: int
    discovery_channel: DiscoveryChannel


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """In-memory SourceDiscoveryEvidence draft (no ORM / no persistence)."""

    run_id: int
    source_telegram_id: int
    source_username: str | None
    source_title: str
    source_type: str
    telegram_message_id: int
    published_at: datetime
    permalink: str | None
    excerpt: str
    normalized_hash: str
    matched_query_ordinals: tuple[int, ...]
    discovery_channels: tuple[DiscoveryChannel, ...]
    detection_category: str
    is_qualified: bool
    hard_exclusion: bool
    hard_exclusion_rule_id: str | None
    service_profiles: tuple[str, ...]
    rule_set_checksum: str

    def matched_query_ordinals_json(self) -> str:
        return json.dumps(list(self.matched_query_ordinals), ensure_ascii=False)

    def discovery_channels_json(self) -> str:
        return json.dumps(list(self.discovery_channels), ensure_ascii=False)

    def service_profiles_json(self) -> str:
        return json.dumps(list(self.service_profiles), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class OpportunitySnapshotRecord:
    """In-memory SourceOpportunitySnapshot draft (no ORM / no persistence)."""

    run_id: int
    source_id: int | None
    source_telegram_id: int
    username: str | None
    title: str
    source_type: str
    public_url: str | None
    linked_parent_telegram_id: int | None
    qualified_count: int
    excluded_count: int
    active_week_count: int
    ecommerce_qualified_count: int
    last_qualified_at: datetime | None
    sample_message_count: int
    sample_timestamps: tuple[datetime, ...]
    score: int
    band: OpportunityBand
    score_components: dict[str, int]
    discovery_channels: tuple[DiscoveryChannel, ...]
    review_state: Literal["unreviewed", "promoted", "dismissed"] = "unreviewed"
    promoted_source_id: int | None = None
    dismiss_reason: str | None = None
    version: int = 1

    def sample_timestamps_json(self) -> str:
        return json.dumps(
            [_iso_z(ts) for ts in self.sample_timestamps],
            ensure_ascii=False,
        )

    def score_components_json(self) -> str:
        return json.dumps(self.score_components, ensure_ascii=False)

    def discovery_channels_json(self) -> str:
        return json.dumps(list(self.discovery_channels), ensure_ascii=False)

    def rank_key(self) -> OpportunityRankKey:
        return OpportunityRankKey(
            score=self.score,
            qualified_count=self.qualified_count,
            active_week_count=self.active_week_count,
            last_qualified_at=self.last_qualified_at,
            telegram_id=self.source_telegram_id,
        )


@dataclass(frozen=True, slots=True)
class PreliminarySourceCandidate:
    """Seed-phase candidate for deep-verification selection (phase G)."""

    telegram_id: int
    source_type: str
    title: str
    username: str | None
    distinct_query_count: int
    seed_evidence_count: int
    directory_title_match: bool
    is_linked_discussion: bool
    freshest_evidence_at: datetime | None
    discovery_channels: tuple[DiscoveryChannel, ...]


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """Aggregated evidence + opportunity snapshots for one run fragment."""

    evidence: tuple[EvidenceRecord, ...]
    opportunities: tuple[OpportunitySnapshotRecord, ...]
    budget_skipped_count: int
    window_skipped_count: int
    registry_suppressed_ids: frozenset[int] = frozenset()
    dismissed_suppressed_ids: frozenset[int] = frozenset()


def resolve_source_identity(
    *,
    telegram_id: int,
    username: str | None,
    registry: SourceRegistryIndex | None = None,
) -> ResolvedSourceIdentity:
    """Apply SRC-022 identity order and return canonical telegram id."""
    username_normalized: str | None = None
    if username:
        try:
            username_normalized = normalize_username(username)
        except ValueError:
            username_normalized = username.strip().lstrip("@").lower() or None

    if registry is not None:
        by_tid = registry.by_telegram_id.get(telegram_id)
        if by_tid is not None:
            return ResolvedSourceIdentity(
                canonical_telegram_id=telegram_id,
                registry_source_id=by_tid.source_id,
                username_normalized=username_normalized or by_tid.username_normalized,
                matched_via="registry_telegram_id",
            )

        if username_normalized:
            by_user = registry.by_username.get(username_normalized)
            if by_user is not None:
                canon = by_user.telegram_id if by_user.telegram_id is not None else telegram_id
                return ResolvedSourceIdentity(
                    canonical_telegram_id=canon,
                    registry_source_id=by_user.source_id,
                    username_normalized=username_normalized,
                    matched_via="username",
                )
            by_alias = registry.by_alias.get(username_normalized)
            if by_alias is not None:
                canon = by_alias.telegram_id if by_alias.telegram_id is not None else telegram_id
                return ResolvedSourceIdentity(
                    canonical_telegram_id=canon,
                    registry_source_id=by_alias.source_id,
                    username_normalized=username_normalized,
                    matched_via="alias",
                )

    if username_normalized:
        return ResolvedSourceIdentity(
            canonical_telegram_id=telegram_id,
            registry_source_id=None,
            username_normalized=username_normalized,
            matched_via="username_fallback",
        )
    return ResolvedSourceIdentity(
        canonical_telegram_id=telegram_id,
        registry_source_id=None,
        username_normalized=None,
        matched_via="telegram_id",
    )


def is_within_evidence_window(
    published_at: datetime,
    *,
    now: datetime,
    window_days: int = EVIDENCE_WINDOW_DAYS,
) -> bool:
    published = _ensure_utc(published_at)
    reference = _ensure_utc(now)
    return published >= reference - timedelta(days=window_days)


def qualify_excerpt_text(
    raw_excerpt: str,
    *,
    detect_fn: DetectFn = detect,
) -> tuple[str, str, DetectionResult]:
    """Normalize text, cap excerpt ≤240, run pure DET detect() (SRC-024)."""
    norms = normalize_message_text(raw_excerpt)
    excerpt = truncate_evidence_excerpt(norms.display_text)
    # Detection uses analysis_text; never retain authors/media beyond excerpt.
    result = detect_fn(norms.analysis_text)
    return excerpt, norms.dedup_hash, result


def evidence_from_hit(
    annotated: AnnotatedSearchHit,
    *,
    run_id: int,
    identity: ResolvedSourceIdentity,
    detect_fn: DetectFn = detect,
) -> EvidenceRecord:
    """Build one evidence draft from a search hit (no pipeline side effects)."""
    hit = annotated.hit
    excerpt, normalized_hash, detection = qualify_excerpt_text(
        hit.excerpt,
        detect_fn=detect_fn,
    )
    return EvidenceRecord(
        run_id=run_id,
        source_telegram_id=identity.canonical_telegram_id,
        source_username=identity.username_normalized or hit.source.username,
        source_title=hit.source.title,
        source_type=hit.source.source_type,
        telegram_message_id=hit.telegram_message_id,
        published_at=_ensure_utc(hit.published_at),
        permalink=hit.permalink,
        excerpt=excerpt,
        normalized_hash=normalized_hash,
        matched_query_ordinals=(annotated.query_ordinal,),
        discovery_channels=(annotated.discovery_channel,),
        detection_category=detection.category,
        is_qualified=detection.is_lead,
        hard_exclusion=detection.hard_exclusion,
        hard_exclusion_rule_id=detection.hard_exclusion_rule_id,
        service_profiles=detection.service_profiles,
        rule_set_checksum=detection.rule_set_checksum,
    )


def merge_evidence_duplicates(
    records: Sequence[EvidenceRecord],
) -> list[EvidenceRecord]:
    """Dedupe by (source_telegram_id, telegram_message_id); merge ordinals/channels."""
    merged: dict[tuple[int, int], EvidenceRecord] = {}
    for record in records:
        key = (record.source_telegram_id, record.telegram_message_id)
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            continue
        ordinals = tuple(
            sorted(set(existing.matched_query_ordinals) | set(record.matched_query_ordinals))
        )
        channel_set = set(existing.discovery_channels) | set(record.discovery_channels)
        channels: tuple[DiscoveryChannel, ...] = tuple(sorted(channel_set, key=_channel_sort_key))
        # Prefer longer excerpt only if still ≤240; keep first detection fields.
        excerpt = existing.excerpt
        if len(record.excerpt) > len(existing.excerpt):
            excerpt = record.excerpt
        merged[key] = EvidenceRecord(
            run_id=existing.run_id,
            source_telegram_id=existing.source_telegram_id,
            source_username=existing.source_username or record.source_username,
            source_title=existing.source_title or record.source_title,
            source_type=existing.source_type,
            telegram_message_id=existing.telegram_message_id,
            published_at=min(existing.published_at, record.published_at),
            permalink=existing.permalink or record.permalink,
            excerpt=excerpt,
            normalized_hash=existing.normalized_hash,
            matched_query_ordinals=ordinals,
            discovery_channels=channels,
            detection_category=existing.detection_category,
            is_qualified=existing.is_qualified or record.is_qualified,
            hard_exclusion=existing.hard_exclusion or record.hard_exclusion,
            hard_exclusion_rule_id=(
                existing.hard_exclusion_rule_id or record.hard_exclusion_rule_id
            ),
            service_profiles=tuple(
                sorted(set(existing.service_profiles) | set(record.service_profiles))
            ),
            rule_set_checksum=existing.rule_set_checksum or record.rule_set_checksum,
        )
    return list(merged.values())


def build_opportunity_from_evidence(
    *,
    run_id: int,
    source: SourceSnapshot,
    evidence: Sequence[EvidenceRecord],
    scored_at: datetime,
    registry_source_id: int | None = None,
    linked_parent_telegram_id: int | None = None,
    extra_discovery_channels: Sequence[DiscoveryChannel] = (),
) -> OpportunitySnapshotRecord:
    """Score unique evidence into one SourceOpportunitySnapshot draft (phase I)."""
    unique = merge_evidence_duplicates(evidence)
    qualified = [e for e in unique if e.is_qualified]
    excluded = [e for e in unique if e.hard_exclusion]
    ecommerce_qualified = [e for e in qualified if ECOMMERCE_SERVICE_CODE in e.service_profiles]
    qualified_timestamps = tuple(e.published_at for e in qualified)
    last_qualified_at = max(qualified_timestamps) if qualified_timestamps else None
    sample_timestamps = tuple(sorted((e.published_at for e in unique), reverse=True))

    score_result: OpportunityScoreResult = score_opportunity(
        qualified_count=len(qualified),
        excluded_count=len(excluded),
        ecommerce_qualified_count=len(ecommerce_qualified),
        last_qualified_at=last_qualified_at,
        scored_at=scored_at,
        qualified_timestamps=qualified_timestamps,
    )

    channels: set[DiscoveryChannel] = set(extra_discovery_channels)
    for row in unique:
        channels.update(row.discovery_channels)
    ordered_channels = tuple(sorted(channels, key=_channel_sort_key))

    return OpportunitySnapshotRecord(
        run_id=run_id,
        source_id=registry_source_id,
        source_telegram_id=source.telegram_id,
        username=source.username,
        title=source.title,
        source_type=source.source_type,
        public_url=source.public_url,
        linked_parent_telegram_id=linked_parent_telegram_id,
        qualified_count=len(qualified),
        excluded_count=len(excluded),
        active_week_count=score_result.active_week_count,
        ecommerce_qualified_count=len(ecommerce_qualified),
        last_qualified_at=last_qualified_at,
        sample_message_count=len(unique),
        sample_timestamps=sample_timestamps,
        score=score_result.total,
        band=score_result.band,
        score_components=score_result.components_dict(),
        discovery_channels=ordered_channels,
    )


def linked_discussion_opportunity(
    *,
    run_id: int,
    parent_telegram_id: int,
    discussion: SourceSnapshot,
    scored_at: datetime,
    registry_source_id: int | None = None,
) -> OpportunitySnapshotRecord:
    """Separate opportunity for a public linked discussion (SRC-023 / phase F)."""
    _ = scored_at  # reserved for worker clock parity with scored snapshots
    return OpportunitySnapshotRecord(
        run_id=run_id,
        source_id=registry_source_id,
        source_telegram_id=discussion.telegram_id,
        username=discussion.username,
        title=discussion.title,
        source_type=discussion.source_type,
        public_url=discussion.public_url,
        linked_parent_telegram_id=parent_telegram_id,
        qualified_count=0,
        excluded_count=0,
        active_week_count=0,
        ecommerce_qualified_count=0,
        last_qualified_at=None,
        sample_message_count=0,
        sample_timestamps=(),
        score=0,
        band="weak",
        score_components={
            "qualified": 0,
            "regularity": 0,
            "ecommerce": 0,
            "recency": 0,
            "noise_penalty": 0,
        },
        discovery_channels=("linked_discussion",),
    )


def preliminary_rank_key(candidate: PreliminarySourceCandidate) -> tuple:
    """Phase G ranking: queries, evidence, directory, type, linked, freshness, id."""
    type_rank = {
        "megagroup": 0,
        "group": 1,
        "channel": 2,
    }.get(candidate.source_type, 3)
    linked_rank = 0 if candidate.is_linked_discussion else 1
    directory_rank = 0 if candidate.directory_title_match else 1
    fresh = (
        -_ensure_utc(candidate.freshest_evidence_at).timestamp()
        if candidate.freshest_evidence_at is not None
        else float("inf")
    )
    return (
        -candidate.distinct_query_count,
        -candidate.seed_evidence_count,
        directory_rank,
        type_rank,
        linked_rank,
        fresh,
        candidate.telegram_id,
    )


def select_sources_for_deep_verification(
    candidates: Sequence[PreliminarySourceCandidate],
    *,
    limit: int = MAX_DEEP_VERIFICATION_SOURCES,
) -> list[PreliminarySourceCandidate]:
    ordered = sorted(candidates, key=preliminary_rank_key)
    return ordered[: max(0, limit)]


def build_preliminary_candidates(
    evidence: Sequence[EvidenceRecord],
    *,
    directory_sources: Sequence[SourceSnapshot] = (),
    directory_query_texts: Sequence[str] = (),
    linked_parent_ids: Mapping[int, int] | None = None,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
) -> list[PreliminarySourceCandidate]:
    """Derive phase-G candidates from seed evidence + directory hits."""
    suppressed = set(registry_telegram_ids(registry)) if registry is not None else set()
    if dismissed is not None:
        suppressed.update(dismissed_telegram_ids(dismissed))
    by_source: dict[int, list[EvidenceRecord]] = {}
    for row in evidence:
        if row.source_telegram_id in suppressed:
            continue
        by_source.setdefault(row.source_telegram_id, []).append(row)

    directory_by_id = {s.telegram_id: s for s in directory_sources}
    query_folded = tuple(q.casefold() for q in directory_query_texts)
    parents = linked_parent_ids or {}

    candidates: dict[int, PreliminarySourceCandidate] = {}
    for telegram_id, rows in by_source.items():
        ordinals = {o for r in rows for o in r.matched_query_ordinals}
        channel_set = {c for r in rows for c in r.discovery_channels}
        channels: tuple[DiscoveryChannel, ...] = tuple(sorted(channel_set, key=_channel_sort_key))
        freshest = max(r.published_at for r in rows)
        meta = rows[0]
        title = meta.source_title
        dir_match = _directory_title_match(title, query_folded)
        if telegram_id in directory_by_id:
            dir_match = dir_match or _directory_title_match(
                directory_by_id[telegram_id].title, query_folded
            )
        candidates[telegram_id] = PreliminarySourceCandidate(
            telegram_id=telegram_id,
            source_type=meta.source_type,
            title=title,
            username=meta.source_username,
            distinct_query_count=len(ordinals),
            seed_evidence_count=len(rows),
            directory_title_match=dir_match,
            is_linked_discussion=telegram_id in parents,
            freshest_evidence_at=freshest,
            discovery_channels=channels,
        )

    for snap in directory_sources:
        if snap.telegram_id in suppressed:
            continue
        if snap.telegram_id in candidates:
            continue
        dir_match = _directory_title_match(snap.title, query_folded)
        candidates[snap.telegram_id] = PreliminarySourceCandidate(
            telegram_id=snap.telegram_id,
            source_type=snap.source_type,
            title=snap.title,
            username=snap.username,
            distinct_query_count=0,
            seed_evidence_count=0,
            directory_title_match=dir_match,
            is_linked_discussion=snap.telegram_id in parents,
            freshest_evidence_at=None,
            discovery_channels=("directory",),
        )
    return list(candidates.values())


def aggregate_search_hits(
    annotated_hits: Sequence[AnnotatedSearchHit],
    *,
    run_id: int,
    scored_at: datetime,
    registry: SourceRegistryIndex | None = None,
    dismissed: DismissedKeywordSourceIndex | None = None,
    detect_fn: DetectFn = detect,
    evidence_cap: int = MAX_EVIDENCE_PER_RUN,
    existing_evidence_count: int = 0,
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
    kept = merged[:remaining]
    budget_skipped = len(merged) - len(kept)

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
    )


def sort_opportunity_snapshots(
    snapshots: Sequence[OpportunitySnapshotRecord],
) -> list[OpportunitySnapshotRecord]:
    keys = [s.rank_key() for s in snapshots]
    ordered_keys = sort_opportunities(keys)
    by_id = {s.source_telegram_id: s for s in snapshots}
    return [by_id[k.telegram_id] for k in ordered_keys]


def _directory_title_match(title: str, queries_folded: Sequence[str]) -> bool:
    folded = title.casefold()
    return any(q and q in folded for q in queries_folded)


def _channel_sort_key(channel: str) -> tuple[int, str]:
    order = {
        "global_message": 0,
        "directory": 1,
        "public_posts": 2,
        "source_verification": 3,
        "linked_discussion": 4,
    }
    return (order.get(channel, 99), channel)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "AggregationResult",
    "AnnotatedSearchHit",
    "DetectFn",
    "DiscoveryChannel",
    "DismissedIdentityMatch",
    "DismissedKeywordSourceEntry",
    "DismissedKeywordSourceIndex",
    "ECOMMERCE_SERVICE_CODE",
    "EVIDENCE_WINDOW_DAYS",
    "EvidenceRecord",
    "MAX_DEEP_VERIFICATION_SOURCES",
    "MAX_EVIDENCE_PER_RUN",
    "MAX_MESSAGES_PER_SOURCE",
    "OpportunitySnapshotRecord",
    "PreliminarySourceCandidate",
    "RegistrySourceEntry",
    "ResolvedSourceIdentity",
    "SourceRegistryIndex",
    "aggregate_search_hits",
    "build_opportunity_from_evidence",
    "build_preliminary_candidates",
    "evidence_from_hit",
    "dismissed_telegram_ids",
    "is_registry_suppressed",
    "is_within_evidence_window",
    "linked_discussion_opportunity",
    "merge_evidence_duplicates",
    "preliminary_rank_key",
    "qualify_excerpt_text",
    "registry_telegram_ids",
    "resolve_dismissed_identity",
    "resolve_source_identity",
    "select_sources_for_deep_verification",
    "sort_opportunity_snapshots",
]
