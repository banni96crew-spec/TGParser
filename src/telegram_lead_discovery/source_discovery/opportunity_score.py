"""Pure Source Opportunity Score (SRC-025 / D-054)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

OpportunityBand = Literal["promising", "review", "weak"]


@dataclass(frozen=True, slots=True)
class OpportunityScoreComponents:
    qualified: int
    regularity: int
    ecommerce: int
    recency: int
    noise_penalty: int


@dataclass(frozen=True, slots=True)
class OpportunityScoreResult:
    total: int
    band: OpportunityBand
    components: OpportunityScoreComponents
    active_week_count: int

    def components_dict(self) -> dict[str, int]:
        return asdict(self.components)


@dataclass(frozen=True, slots=True)
class OpportunityRankKey:
    """Sort key fields for deterministic opportunity ranking (SRC-025)."""

    score: int
    qualified_count: int
    active_week_count: int
    last_qualified_at: datetime | None
    telegram_id: int


def clamp_score(value: int | float, *, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, math.floor(value) if isinstance(value, float) else value)))


def qualified_component(qualified_count: int) -> int:
    """Qualified messages dimension: 0–40."""
    if qualified_count <= 0:
        return 0
    if qualified_count == 1:
        return 8
    if qualified_count == 2:
        return 16
    if qualified_count == 3:
        return 24
    if qualified_count == 4:
        return 32
    return 40


def regularity_component(active_week_count: int) -> int:
    """Regularity by distinct calendar weeks with qualified messages: 0–25."""
    if active_week_count <= 0:
        return 0
    if active_week_count == 1:
        return 8
    if active_week_count == 2:
        return 14
    if active_week_count == 3:
        return 20
    return 25


def ecommerce_component(ecommerce_qualified_count: int) -> int:
    """E-commerce dimension: min(20, count × 5)."""
    return min(20, max(0, ecommerce_qualified_count) * 5)


def recency_component(
    last_qualified_at: datetime | None,
    *,
    scored_at: datetime,
) -> int:
    """Recency vs scored_at: ≤3d→15, 4–7→10, 8–14→5, >14→0."""
    if last_qualified_at is None:
        return 0
    last = _ensure_utc(last_qualified_at)
    now = _ensure_utc(scored_at)
    age_days = max(0, int((now - last).total_seconds() // 86400))
    if age_days <= 3:
        return 15
    if age_days <= 7:
        return 10
    if age_days <= 14:
        return 5
    return 0


def noise_penalty_component(*, qualified_count: int, excluded_count: int) -> int:
    """Noise: floor(30 × excluded / max(1, qualified + excluded))."""
    q = max(0, qualified_count)
    e = max(0, excluded_count)
    return math.floor(30 * e / max(1, q + e))


def active_weeks(qualified_timestamps: Sequence[datetime]) -> int:
    """Count distinct UTC ISO calendar weeks with at least one qualified message."""
    weeks: set[tuple[int, int]] = set()
    for ts in qualified_timestamps:
        utc_ts = _ensure_utc(ts)
        iso = utc_ts.isocalendar()
        weeks.add((iso.year, iso.week))
    return len(weeks)


def band_for_score(total: int) -> OpportunityBand:
    if total >= 60:
        return "promising"
    if total >= 35:
        return "review"
    return "weak"


def score_opportunity(
    *,
    qualified_count: int,
    excluded_count: int,
    ecommerce_qualified_count: int,
    last_qualified_at: datetime | None,
    scored_at: datetime,
    qualified_timestamps: Sequence[datetime] | None = None,
    active_week_count: int | None = None,
) -> OpportunityScoreResult:
    """Compute deterministic opportunity score and band (SRC-025)."""
    if active_week_count is None:
        stamps = qualified_timestamps if qualified_timestamps is not None else ()
        week_count = active_weeks(stamps)
    else:
        week_count = active_week_count

    components = OpportunityScoreComponents(
        qualified=qualified_component(qualified_count),
        regularity=regularity_component(week_count),
        ecommerce=ecommerce_component(ecommerce_qualified_count),
        recency=recency_component(last_qualified_at, scored_at=scored_at),
        noise_penalty=noise_penalty_component(
            qualified_count=qualified_count,
            excluded_count=excluded_count,
        ),
    )
    raw = (
        components.qualified
        + components.regularity
        + components.ecommerce
        + components.recency
        - components.noise_penalty
    )
    total = clamp_score(raw)
    return OpportunityScoreResult(
        total=total,
        band=band_for_score(total),
        components=components,
        active_week_count=week_count,
    )


def opportunity_sort_key(item: OpportunityRankKey) -> tuple:
    """Tie-break: score DESC, qualified DESC, weeks DESC, last_qualified DESC, id ASC."""
    last = item.last_qualified_at
    # None sorts last when using reverse chronological: use sentinel min datetime.
    last_key = _ensure_utc(last).timestamp() if last is not None else float("-inf")
    return (
        -item.score,
        -item.qualified_count,
        -item.active_week_count,
        -last_key,
        item.telegram_id,
    )


def sort_opportunities(items: Sequence[OpportunityRankKey]) -> list[OpportunityRankKey]:
    return sorted(items, key=opportunity_sort_key)


@dataclass(frozen=True, slots=True)
class OpportunityEligibilityResult:
    """Score/band after SRC-043/045 evidence and profile eligibility gates."""

    score: int
    band: OpportunityBand
    reason_codes: tuple[str, ...]


def apply_opportunity_eligibility(
    *,
    score_result: OpportunityScoreResult,
    discovery_channels: Sequence[str],
    has_message_evidence: bool,
    has_verification_evidence: bool,
    is_linked_discussion: bool,
    matched_service_profiles: Sequence[str] = (),
    required_service_profiles: Sequence[str] = (),
) -> OpportunityEligibilityResult:
    """Cap band/score when evidence or required service profiles are missing."""
    reasons: list[str] = []
    score = score_result.total
    band = score_result.band
    channels = tuple(discovery_channels)
    channel_set = set(channels)

    directory_only = (
        bool(channel_set)
        and channel_set.issubset({"directory"})
        and not has_message_evidence
    )
    if directory_only:
        reasons.append("directory_only_no_evidence")
        score = min(score, 34)
        band = "weak"

    needs_verification = (
        (is_linked_discussion or not has_verification_evidence)
        and not has_message_evidence
        and not directory_only
    )
    if needs_verification or (
        not has_verification_evidence
        and not has_message_evidence
        and is_linked_discussion
    ):
        if "needs_verification" not in reasons:
            reasons.append("needs_verification")
        score = min(score, 34)
        band = "weak"

    required = tuple(s.strip().casefold() for s in required_service_profiles if s.strip())
    matched = {s.strip().casefold() for s in matched_service_profiles if s.strip()}
    for svc in required:
        if svc not in matched:
            reasons.append(f"required_service_profile_miss:{svc}")
            # Soft penalty: force below review floor when required profile missing.
            score = min(score, 34)
            band = "weak"

    if band in ("review", "promising") and (
        directory_only or ("needs_verification" in reasons)
    ):
        score = min(score, 34)
        band = "weak"

    return OpportunityEligibilityResult(
        score=score,
        band=band,
        reason_codes=tuple(reasons),
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "OpportunityBand",
    "OpportunityEligibilityResult",
    "OpportunityRankKey",
    "OpportunityScoreComponents",
    "OpportunityScoreResult",
    "active_weeks",
    "apply_opportunity_eligibility",
    "band_for_score",
    "clamp_score",
    "ecommerce_component",
    "noise_penalty_component",
    "opportunity_sort_key",
    "qualified_component",
    "recency_component",
    "regularity_component",
    "score_opportunity",
    "sort_opportunities",
]
