"""Terminal truth and score evaluation for ActiveClientChat v1."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from telegram_lead_discovery.source_discovery.active_chat import (
    COMPLETE_REASONS,
    FRESHNESS_WINDOW_DAYS,
    INCOMPLETE_REASONS,
    MIN_ACTIVITY_AUTHORS,
    MIN_ACTIVITY_DAYS,
    MIN_ACTIVITY_MESSAGES,
    MIN_CLIENT_AUTHORS,
    MIN_CLIENT_REQUESTS,
    ActiveChatCounters,
    OpportunityBand,
    TerminalStopReason,
    TruthStatus,
    ensure_utc,
)


@dataclass(frozen=True, slots=True)
class ActiveChatEvaluation:
    truth_status: TruthStatus
    score: int
    band: OpportunityBand
    score_components: dict[str, int]
    qualification_reasons: tuple[str, ...]
    thresholds: dict[str, bool]


def _tier(value: int, values: tuple[int, int, int, int]) -> int:
    return values[0] if value <= 0 else values[min(value, 3)]


def evaluate_active_client_chat(
    counters: ActiveChatCounters,
    *,
    reference_at: datetime,
    stop_reason: TerminalStopReason,
    required_service_profiles: tuple[str, ...] = (),
) -> ActiveChatEvaluation:
    if stop_reason not in INCOMPLETE_REASONS | COMPLETE_REASONS | {"quality_reached"}:
        raise ValueError(f"non_terminal_stop_reason:{stop_reason}")
    reference = ensure_utc(reference_at)
    latest = (
        ensure_utc(counters.latest_client_request_at) if counters.latest_client_request_at else None
    )
    thresholds = active_chat_thresholds(counters, reference_at=reference)
    matched = set(counters.matched_service_profiles)
    required_misses = tuple(
        service for service in required_service_profiles if service not in matched
    )
    quality = all(thresholds.values()) and not required_misses
    if quality:
        truth: TruthStatus = "quality"
    elif stop_reason in INCOMPLETE_REASONS:
        truth = "inconclusive"
    elif stop_reason in COMPLETE_REASONS:
        truth = "near" if counters.client_request_count else "rejected"
    else:
        raise ValueError(f"invalid_terminal_stop_reason:{stop_reason}")

    reasons: list[str] = []
    reason_map = (
        ("activity_messages", "activity_messages_below_100"),
        ("activity_days", "activity_days_below_10"),
        ("activity_authors", "activity_authors_below_20"),
        ("client_requests", "client_requests_below_3"),
        ("client_authors", "client_authors_below_3"),
        ("freshness", "latest_request_older_than_7d"),
    )
    if quality:
        reasons.append("quality_pass")
    else:
        reasons.extend(reason for key, reason in reason_map if not thresholds[key])
        if stop_reason in INCOMPLETE_REASONS:
            reasons.append(f"{stop_reason}_incomplete")
    reasons.extend(f"required_service_profile_miss:{service}" for service in required_misses)
    if counters.profile_excluded_count:
        reasons.append(f"profile_additional_exclusion_matches:{counters.profile_excluded_count}")

    age_days = (reference - latest).total_seconds() / 86400 if latest else math.inf
    recency = 15 if age_days <= 3 else 10 if age_days <= 7 else 5 if age_days <= 30 else 0
    components = {
        "requests": _tier(counters.client_request_count, (0, 12, 24, 40)),
        "client_authors": _tier(counters.client_request_author_count, (0, 8, 16, 25)),
        "activity_messages": min(8, 8 * max(0, counters.activity_message_count) // 100),
        "activity_days": min(6, 6 * max(0, counters.activity_active_day_count) // 10),
        "activity_authors": min(6, 6 * max(0, counters.activity_distinct_author_count) // 20),
        "recency": recency,
        "noise_penalty": 30
        * max(0, counters.hard_excluded_count)
        // max(1, counters.client_request_count + counters.hard_excluded_count),
    }
    positive = sum(value for key, value in components.items() if key != "noise_penalty")
    total = max(0, min(100, positive - components["noise_penalty"]))
    band: OpportunityBand = (
        "promising"
        if truth == "quality" and total >= 60
        else "review"
        if truth == "near" and total >= 35
        else "weak"
    )
    return ActiveChatEvaluation(truth, total, band, components, tuple(reasons), thresholds)


def active_chat_thresholds(
    counters: ActiveChatCounters,
    *,
    reference_at: datetime,
) -> dict[str, bool]:
    reference = ensure_utc(reference_at)
    latest = (
        ensure_utc(counters.latest_client_request_at) if counters.latest_client_request_at else None
    )
    return {
        "activity_messages": counters.activity_message_count >= MIN_ACTIVITY_MESSAGES,
        "activity_days": counters.activity_active_day_count >= MIN_ACTIVITY_DAYS,
        "activity_authors": counters.activity_distinct_author_count >= MIN_ACTIVITY_AUTHORS,
        "client_requests": counters.client_request_count >= MIN_CLIENT_REQUESTS,
        "client_authors": counters.client_request_author_count >= MIN_CLIENT_AUTHORS,
        "freshness": bool(latest and latest >= reference - timedelta(days=FRESHNESS_WINDOW_DAYS)),
    }


def counters_dict(counters: ActiveChatCounters) -> dict[str, object]:
    return asdict(counters)


__all__ = [
    "ActiveChatEvaluation",
    "active_chat_thresholds",
    "counters_dict",
    "evaluate_active_client_chat",
]
