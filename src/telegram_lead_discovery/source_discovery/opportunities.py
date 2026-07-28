"""Pure opportunity construction and scoring for keyword discovery."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from telegram_lead_discovery.collector.ports import SourceSnapshot
from telegram_lead_discovery.source_discovery.evidence import (
    DiscoveryChannel,
    EvidenceRecord,
    _channel_sort_key,
    _iso_z,
    merge_evidence_duplicates,
)
from telegram_lead_discovery.source_discovery.keyword_profiles import match_additional_exclusion
from telegram_lead_discovery.source_discovery.opportunity_score import (
    OpportunityBand,
    OpportunityRankKey,
    OpportunityScoreResult,
    apply_opportunity_eligibility,
    score_opportunity,
)

ECOMMERCE_SERVICE_CODE = "ecommerce"


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
    score_components: dict[str, object]
    discovery_channels: tuple[DiscoveryChannel, ...]
    review_state: Literal["unreviewed", "promoted", "dismissed"] = "unreviewed"
    promoted_source_id: int | None = None
    dismiss_reason: str | None = None
    version: int = 1
    truth_status: Literal["quality", "near", "inconclusive", "rejected"] = "inconclusive"
    verification_scanned_count: int = 0
    verification_stop_reason: str | None = None

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


def build_opportunity_from_evidence(
    *,
    run_id: int,
    source: SourceSnapshot,
    evidence: Sequence[EvidenceRecord],
    scored_at: datetime,
    registry_source_id: int | None = None,
    linked_parent_telegram_id: int | None = None,
    extra_discovery_channels: Sequence[DiscoveryChannel] = (),
    required_service_profiles: Sequence[str] = (),
    additional_exclusions: Sequence[str] = (),
) -> OpportunitySnapshotRecord:
    """Score unique evidence into one SourceOpportunitySnapshot draft (phase I)."""
    unique = merge_evidence_duplicates(evidence)
    qualified = [e for e in unique if e.is_qualified]
    excluded = [e for e in unique if e.hard_exclusion]
    # Profile additional exclusions count as soft exclusions with explainable reasons.
    exclusion_reasons: list[str] = []
    if additional_exclusions:
        for row in unique:
            reason = match_additional_exclusion(row.excerpt, additional_exclusions)
            if reason is not None:
                exclusion_reasons.append(reason)
                if row not in excluded:
                    excluded.append(row)
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

    matched_services = tuple(sorted({s for e in unique for s in e.service_profiles}))
    has_message = len(unique) > 0
    has_verification = "source_verification" in ordered_channels or any(
        c in ordered_channels for c in ("global_message", "public_posts")
    )
    gated = apply_opportunity_eligibility(
        score_result=score_result,
        discovery_channels=ordered_channels,
        has_message_evidence=has_message,
        has_verification_evidence=has_verification,
        is_linked_discussion=linked_parent_telegram_id is not None,
        matched_service_profiles=matched_services,
        required_service_profiles=required_service_profiles,
    )
    components: dict[str, object] = dict(score_result.components_dict())
    reason_codes = list(gated.reason_codes)
    reason_codes.extend(exclusion_reasons)
    if reason_codes:
        components["eligibility_reasons"] = reason_codes
        components["reason_codes"] = reason_codes

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
        score=gated.score,
        band=gated.band,
        score_components=components,
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
            "eligibility_reasons": ["needs_verification"],
            "reason_codes": ["needs_verification"],
        },
        discovery_channels=("linked_discussion",),
    )



__all__ = [
    "ECOMMERCE_SERVICE_CODE",
    "OpportunitySnapshotRecord",
    "build_opportunity_from_evidence",
    "linked_discussion_opportunity",
]

