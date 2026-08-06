"""Build persisted scouting evidence from one classified history message."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.source_discovery.active_chat import (
    ActiveChatMessage,
    source_scoped_author_key,
)
from telegram_lead_discovery.source_discovery.evidence import EvidenceRecord, qualify_excerpt_text
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    match_additional_exclusion,
)


def _profile_exclusion(
    text: str,
    additional_exclusions: Sequence[str],
    detection: Any,
) -> tuple[bool, str | None]:
    matched = match_additional_exclusion(text, additional_exclusions)
    reason = f"profile_exclusion:{matched}" if matched else detection.hard_exclusion_rule_id
    return bool(detection.hard_exclusion or matched), reason


def _profile_exclusion_reason(reason: str | None) -> str | None:
    return reason if reason and reason.startswith("profile_exclusion:") else None


@dataclass(frozen=True, slots=True)
class HistoryClassification:
    excerpt: str
    normalized_hash: str
    detection: Any
    active_message: ActiveChatMessage
    exclusion_reason: str | None


def _classify_history_message(
    ctx: Any,
    *,
    telegram_id: int,
    dto: Any,
    published_at: datetime,
) -> HistoryClassification:
    excerpt, normalized_hash, detection = qualify_excerpt_text(
        dto.text or "",
        detect_fn=lambda text: detect(
            text,
            rules=ctx.detection_rules,
            rule_set_checksum=ctx.rule_set_checksum,
        ),
    )
    hard_exclusion, exclusion_reason = _profile_exclusion(
        dto.text or "", ctx.additional_exclusions, detection
    )
    author_kind = dto.author_kind
    author_key = None
    if author_kind == "user" and dto.author_peer_id is not None:
        author_key = source_scoped_author_key(telegram_id, dto.author_peer_id)
    elif author_kind == "user":
        author_kind = "unknown"
    message = ActiveChatMessage(
        telegram_message_id=int(dto.telegram_message_id),
        published_at=published_at,
        normalized_hash=normalized_hash,
        author_kind=author_kind,
        author_key=author_key,
        detection_category=detection.category,
        service_profiles=tuple(detection.service_profiles),
        hard_exclusion=hard_exclusion,
        profile_exclusion_reason=_profile_exclusion_reason(exclusion_reason),
    )
    return HistoryClassification(excerpt, normalized_hash, detection, message, exclusion_reason)


def _history_evidence_record(
    *,
    run_id: int,
    telegram_id: int,
    username: str | None,
    title: str,
    source_type: str,
    dto: Any,
    excerpt: str,
    normalized_hash: str,
    detection: Any,
    query_ordinal: int,
    client: bool,
    author_key: str | None,
    author_kind: str,
    hard_exclusion: bool,
    exclusion_reason: str | None,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=run_id,
        source_telegram_id=telegram_id,
        source_username=username,
        source_title=title,
        source_type=source_type,
        telegram_message_id=int(dto.telegram_message_id),
        published_at=dto.published_at,
        permalink=dto.permalink,
        excerpt=excerpt,
        normalized_hash=normalized_hash,
        matched_query_ordinals=(query_ordinal,),
        discovery_channels=("source_verification",),
        detection_category=detection.category,
        is_qualified=client,
        hard_exclusion=hard_exclusion,
        hard_exclusion_rule_id=exclusion_reason,
        service_profiles=detection.service_profiles,
        rule_set_checksum=detection.rule_set_checksum,
        matched_rule_ids=tuple(m.stable_rule_id for m in detection.matched_rules),
        author_key=author_key,
        author_kind=author_kind,
    )


__all__ = [
    "_classify_history_message",
    "_history_evidence_record",
    "_profile_exclusion",
    "_profile_exclusion_reason",
]
