"""Pure keyword evidence qualification and deduplication."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from telegram_lead_discovery.collector.ports import SearchMessageHitDTO
from telegram_lead_discovery.detection.engine import DetectionResult, seed_catalog_detect
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.source_discovery.identity import ResolvedSourceIdentity, _ensure_utc
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    truncate_evidence_excerpt,
)
from telegram_lead_discovery.source_discovery.quality_truth import (
    HISTORY_CAP_PER_RUN,
    HISTORY_CAP_PER_SOURCE,
    QUALITY_MIN_DISTINCT_CLIENT_REQUESTS,
    QUALITY_WINDOW_DAYS,
)

DiscoveryChannel = Literal[
    "global_message",
    "directory",
    "public_posts",
    "source_verification",
    "linked_discussion",
]

# Evidence budget (D-068): qualified client evidence has absolute priority over noise.
# Documented raise from historical 500 so 5×7 gate identities + bounded noise coexist.
MAX_EVIDENCE_PER_RUN = 500
MAX_QUALIFIED_EVIDENCE_PER_RUN = 200
MAX_NOISE_EVIDENCE_PER_RUN = 100
# Soft initial deep-verification preference; worker continues ranked pool until
# gate (5×35) OR pool exhausted OR run history cap 7500 (SRC-040 / D-068).
# Legacy phrase-search cap (compat); history scan uses HISTORY_SCAN_CAP_*.
MAX_MESSAGES_PER_SOURCE = 20
EVIDENCE_WINDOW_DAYS = QUALITY_WINDOW_DAYS
HISTORY_SCAN_CAP_PER_SOURCE = HISTORY_CAP_PER_SOURCE
HISTORY_SCAN_CAP_PER_RUN = HISTORY_CAP_PER_RUN
QUALITY_DISTINCT_MIN = QUALITY_MIN_DISTINCT_CLIENT_REQUESTS
DetectFn = Callable[[str], DetectionResult]


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
    matched_rule_ids: tuple[str, ...] = ()

    def matched_query_ordinals_json(self) -> str:
        return json.dumps(list(self.matched_query_ordinals), ensure_ascii=False)

    def discovery_channels_json(self) -> str:
        return json.dumps(list(self.discovery_channels), ensure_ascii=False)

    def service_profiles_json(self) -> str:
        return json.dumps(list(self.service_profiles), ensure_ascii=False)

    def matched_rule_ids_json(self) -> str:
        return json.dumps(list(self.matched_rule_ids), ensure_ascii=False)


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
    detect_fn: DetectFn = seed_catalog_detect,
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
    detect_fn: DetectFn = seed_catalog_detect,
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
        matched_rule_ids=tuple(m.stable_rule_id for m in detection.matched_rules),
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
            matched_rule_ids=tuple(
                sorted(set(existing.matched_rule_ids) | set(record.matched_rule_ids))
            ),
        )
    return list(merged.values())


def _channel_sort_key(channel: str) -> tuple[int, str]:
    order = {
        "global_message": 0,
        "directory": 1,
        "public_posts": 2,
        "source_verification": 3,
        "linked_discussion": 4,
    }
    return (order.get(channel, 99), channel)


def _iso_z(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")



__all__ = [
    "AnnotatedSearchHit",
    "DetectFn",
    "DiscoveryChannel",
    "EVIDENCE_WINDOW_DAYS",
    "EvidenceRecord",
    "HISTORY_SCAN_CAP_PER_RUN",
    "HISTORY_SCAN_CAP_PER_SOURCE",
    "MAX_EVIDENCE_PER_RUN",
    "MAX_MESSAGES_PER_SOURCE",
    "MAX_NOISE_EVIDENCE_PER_RUN",
    "MAX_QUALIFIED_EVIDENCE_PER_RUN",
    "QUALITY_DISTINCT_MIN",
    "evidence_from_hit",
    "is_within_evidence_window",
    "merge_evidence_duplicates",
    "qualify_excerpt_text",
]
