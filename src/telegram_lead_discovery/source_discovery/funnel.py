"""Pure funnel counter and neutral-noise transformations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

from telegram_lead_discovery.source_discovery.opportunities import OpportunitySnapshotRecord
from telegram_lead_discovery.source_discovery.opportunity_score import score_opportunity

POOL_EXHAUSTED_REASON_CODES: dict[str, int] = {
    "provider_empty": 0,
    "no_unseen_after_suppress": 1,
}

def apply_neutral_noise_sample(
    base: OpportunitySnapshotRecord,
    *,
    neutral_excluded_count: int,
    neutral_sample_count: int,
    scored_at: datetime | None = None,
) -> OpportunitySnapshotRecord:
    """Re-score opportunity after bounded neutral (non-query-hit) noise sample."""
    _ = neutral_sample_count  # sample size is observational; exclusions drive penalty
    new_excluded = base.excluded_count + max(0, neutral_excluded_count)
    when = scored_at or (
        base.last_qualified_at if base.last_qualified_at is not None else datetime.now(UTC)
    )
    score_result = score_opportunity(
        qualified_count=base.qualified_count,
        excluded_count=new_excluded,
        ecommerce_qualified_count=base.ecommerce_qualified_count,
        last_qualified_at=base.last_qualified_at,
        scored_at=when,
        active_week_count=base.active_week_count,
    )
    components: dict[str, object] = dict(score_result.components_dict())
    prior_reasons = base.score_components.get("eligibility_reasons") or base.score_components.get(
        "reason_codes"
    )
    reasons: list[str] = []
    if isinstance(prior_reasons, list):
        reasons.extend(str(r) for r in prior_reasons)
    reasons.append("neutral_noise_sample")
    components["eligibility_reasons"] = reasons
    components["reason_codes"] = reasons
    return replace(
        base,
        excluded_count=new_excluded,
        sample_message_count=base.sample_message_count + max(0, neutral_sample_count),
        score=score_result.total,
        band=score_result.band,
        score_components=components,
    )


def merge_funnel_counters(
    base: Mapping[str, int | str] | None = None,
    *,
    acquired_total: int | None = None,
    canonicalized_total: int | None = None,
    registry_suppressed: int | None = None,
    dismissed_suppressed: int | None = None,
    duplicate_in_run: int | None = None,
    cooldown_suppressed: int | None = None,
    presented_suppressed: int | None = None,
    suppressed_total: int | None = None,
    qualified_total: int | None = None,
    presented_total: int | None = None,
    novel_presented_total: int | None = None,
    replacement_fetches_total: int | None = None,
    pool_exhausted: bool | None = None,
    pool_exhausted_reason: str | None = None,
) -> dict[str, int | str]:
    """Merge SRC-037 funnel counters; novelty in basis points (×10000)."""
    out: dict[str, int | str] = {}
    for k, v in (base or {}).items():
        key = str(k)
        if isinstance(v, str):
            out[key] = v
        else:
            out[key] = int(v)
    updates = {
        "acquired_total": acquired_total,
        "canonicalized_total": canonicalized_total,
        "registry_suppressed": registry_suppressed,
        "dismissed_suppressed": dismissed_suppressed,
        "duplicate_in_run": duplicate_in_run,
        "cooldown_suppressed": cooldown_suppressed,
        "presented_suppressed": presented_suppressed,
        "suppressed_total": suppressed_total,
        "qualified_total": qualified_total,
        "presented_total": presented_total,
        "novel_presented_total": novel_presented_total,
        "replacement_fetches_total": replacement_fetches_total,
    }
    for key, value in updates.items():
        if value is not None:
            out[key] = int(value)
    # D-069: cooldown_suppressed is historical alias of presented_suppressed (unique peers).
    if presented_suppressed is not None and cooldown_suppressed is None:
        out["cooldown_suppressed"] = int(presented_suppressed)
    elif cooldown_suppressed is not None and presented_suppressed is None:
        out["presented_suppressed"] = int(cooldown_suppressed)
    elif presented_suppressed is not None and cooldown_suppressed is not None:
        # Prefer presented; keep both equal to the same unique count.
        synced = int(presented_suppressed)
        out["presented_suppressed"] = synced
        out["cooldown_suppressed"] = synced
    if pool_exhausted is not None:
        out["pool_exhausted"] = 1 if pool_exhausted else 0
    if pool_exhausted_reason is not None:
        out["pool_exhausted_reason_code"] = POOL_EXHAUSTED_REASON_CODES.get(
            pool_exhausted_reason, -1
        )
    presented = int(out.get("presented_total", 0) or 0)
    novel = int(out.get("novel_presented_total", 0) or 0)
    out["novelty_ratio_bp"] = int(10000 * novel / max(1, presented))
    return out



__all__ = [
    "POOL_EXHAUSTED_REASON_CODES",
    "apply_neutral_noise_sample",
    "merge_funnel_counters",
]
