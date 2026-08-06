"""Truthful exhaustion classification for bounded acquisition paths."""

from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _cursor_payload,
    _loads_counters,
    _WorkerContext,
)
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    RUNTIME_CONFIG,
    DiscoveryRunQuery,
    select,
)


async def _classify_acquisition_stop(
    ctx: _WorkerContext,
    *,
    pool_size: int,
    acquired_total: int,
) -> tuple[bool, str | None, str]:
    """Return pool_exhausted, exhaustion reason, run termination reason."""
    if pool_size >= RUNTIME_CONFIG.MAX_DEEP_VERIFICATION_SOURCES:
        return False, None, "deep_candidate_cap"
    if int(_loads_counters(ctx.run.counters_json).get("budget_skipped", 0)) > 0:
        return False, None, "acquisition_budget_cap"

    rows = list(
        (
            await ctx.session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == ctx.run.id,
                    DiscoveryRunQuery.query_kind.in_(
                        ("global_message", "directory", "public_posts")
                    ),
                )
            )
        ).scalars()
    )
    if any(row.state in ("queued", "running", "retry_wait") for row in rows):
        return False, None, "acquisition_budget_cap"
    if any(row.state == "quota_skipped" for row in rows):
        return False, None, "quota_skipped_remaining"
    if any(row.state in ("failed", "budget_skipped", "cancelled") for row in rows):
        return False, None, "acquisition_budget_cap"

    for row in rows:
        payload = _cursor_payload(row.cursor_json)
        if row.query_kind in ("global_message", "public_posts") and payload.get("token"):
            return False, None, "acquisition_budget_cap"
        if row.query_kind == "directory" and not payload.get("provider_exhausted", False):
            return False, None, "acquisition_budget_cap"

    reason = "provider_empty" if acquired_total == 0 else "no_unseen_after_suppress"
    return True, reason, reason


__all__ = ["_classify_acquisition_stop"]
