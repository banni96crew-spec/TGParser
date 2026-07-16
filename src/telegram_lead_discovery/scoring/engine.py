"""Lead scoring engine (SCR-001..SCR-014)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.detection.engine import DetectionResult

DIMENSION_CAPS: dict[str, int] = {
    "intent": 25,
    "service_fit": 20,
    "specificity": 15,
    "budget": 10,
    "deadline": 5,
    "urgency": 5,
    "readiness": 5,
    "contactability": 5,
    "freshness": 5,
    "source_quality": 5,
}

SOFT_PENALTY_CAP = -30
HOT_MIN = 70
WARM_MIN = 50
COLD_MIN = 30


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    rule_id: str | None
    dimension: str
    value: int
    reason_ru: str


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total: int
    band: str
    raw_total: int
    soft_penalty_total: int
    hard_exclusion: bool
    hard_exclusion_rule_id: str | None
    components: tuple[ScoreComponent, ...]
    create_lead: bool


def freshness_points(published_at: datetime, scored_at: datetime) -> int:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    if scored_at.tzinfo is None:
        scored_at = scored_at.replace(tzinfo=UTC)
    age = scored_at - published_at
    if age <= timedelta(hours=1):
        return 5
    if age <= timedelta(hours=6):
        return 4
    if age <= timedelta(hours=24):
        return 3
    if age <= timedelta(hours=72):
        return 2
    if age <= timedelta(days=14):
        return 1
    return 0


def band_for_total(
    total: int,
    *,
    hot_min: int = HOT_MIN,
    warm_min: int = WARM_MIN,
    cold_min: int = COLD_MIN,
) -> str:
    if total >= hot_min:
        return "hot"
    if total >= warm_min:
        return "warm"
    if total >= cold_min:
        return "cold"
    return "irrelevant"


def score_detection(
    detection: DetectionResult,
    *,
    published_at: datetime,
    source_quality_score: int,
    scored_at: datetime | None = None,
    hot_min: int = HOT_MIN,
    warm_min: int = WARM_MIN,
    cold_min: int = COLD_MIN,
) -> ScoreResult:
    now = scored_at or datetime.now(UTC)

    if detection.hard_exclusion or detection.category in {"spam", "advertising", "vacancy"}:
        return ScoreResult(
            total=0,
            band="irrelevant",
            raw_total=0,
            soft_penalty_total=0,
            hard_exclusion=True,
            hard_exclusion_rule_id=detection.hard_exclusion_rule_id,
            components=(),
            create_lead=False,
        )

    if not detection.is_lead:
        return ScoreResult(
            total=0,
            band="irrelevant",
            raw_total=0,
            soft_penalty_total=0,
            hard_exclusion=False,
            hard_exclusion_rule_id=None,
            components=(),
            create_lead=False,
        )

    dim_sums: dict[str, int] = {
        key: 0 for key in DIMENSION_CAPS if key not in {"freshness", "source_quality"}
    }
    soft_penalty = 0
    seen: set[str] = set()
    components: list[ScoreComponent] = []

    for rule in detection.matched_rules:
        if rule.stable_rule_id in seen:
            continue
        seen.add(rule.stable_rule_id)
        if rule.dimension == "hard_exclusion":
            continue
        if rule.dimension == "soft_penalty":
            value = rule.weight if rule.weight <= 0 else -abs(rule.weight)
            soft_penalty += value
            components.append(
                ScoreComponent(
                    rule_id=rule.stable_rule_id,
                    dimension="soft_penalty",
                    value=value,
                    reason_ru=rule.explanation_code,
                )
            )
            continue
        if rule.dimension not in dim_sums:
            continue
        dim_sums[rule.dimension] += max(0, rule.weight)
        components.append(
            ScoreComponent(
                rule_id=rule.stable_rule_id,
                dimension=rule.dimension,
                value=rule.weight,
                reason_ru=rule.explanation_code,
            )
        )

    for dim, cap in DIMENSION_CAPS.items():
        if dim in dim_sums:
            dim_sums[dim] = min(dim_sums[dim], cap)

    fresh = freshness_points(published_at, now)
    quality = max(0, min(5, int(source_quality_score)))
    components.append(
        ScoreComponent(rule_id=None, dimension="freshness", value=fresh, reason_ru="freshness")
    )
    components.append(
        ScoreComponent(
            rule_id=None,
            dimension="source_quality",
            value=quality,
            reason_ru="source_quality",
        )
    )

    soft_penalty_total = max(SOFT_PENALTY_CAP, soft_penalty)
    positive_total = sum(dim_sums.values()) + fresh + quality
    total = max(0, min(100, positive_total + soft_penalty_total))
    band = band_for_total(total, hot_min=hot_min, warm_min=warm_min, cold_min=cold_min)
    return ScoreResult(
        total=total,
        band=band,
        raw_total=positive_total,
        soft_penalty_total=soft_penalty_total,
        hard_exclusion=False,
        hard_exclusion_rule_id=None,
        components=tuple(components),
        create_lead=band in {"hot", "warm", "cold"},
    )
