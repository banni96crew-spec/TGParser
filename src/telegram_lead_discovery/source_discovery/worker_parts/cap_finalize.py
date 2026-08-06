from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _dumps_counters,
    _loads_counters,
    _save_cursor,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import _load_history_cursor
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _TERMINAL_VERIFICATION_STATES,
    _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.truth_state import _apply_source_truth


async def _finalize_unfinished_on_run_cap(
    ctx: _WorkerContext,
    *,
    pool: list[dict[str, Any]],
    done_sources: set[int],
    suppressed_ids: set[int],
) -> None:
    """Mark unfinished pool sources inconclusive when run soft-cap stops verification."""
    counters = _loads_counters(ctx.run.counters_json)
    counters["hit_run_cap"] = 1
    ctx.run.counters_json = _dumps_counters(counters)

    for item in pool:
        tid = int(item["telegram_id"])
        if tid in done_sources or tid in suppressed_ids:
            continue
        result = await ctx.session.execute(
            select(DiscoveryRunQuery)
            .where(
                DiscoveryRunQuery.run_id == ctx.run.id,
                DiscoveryRunQuery.query_kind == "source_verification",
                DiscoveryRunQuery.source_telegram_id == tid,
            )
            .order_by(DiscoveryRunQuery.ordinal.asc())
            .limit(1)
        )
        query = result.scalar_one_or_none()
        scanned = 0
        distinct = 0
        if query is not None:
            cursor = _load_history_cursor(query)
            scanned = int(cursor.get("scanned", 0) or 0)
            distinct = len(cursor.get("distinct_hashes", []) or [])
            if query.state not in _TERMINAL_VERIFICATION_STATES:
                _save_cursor(
                    query,
                    {
                        **cursor,
                        "stop_reason": "run_cap",
                    },
                )
                await _mark_query_terminal(query, "succeeded")
        await _apply_source_truth(
            ctx,
            telegram_id=tid,
            distinct_count=distinct,
            scanned=scanned,
            window_complete=False,
            hit_source_cap=False,
            hit_run_cap=True,
            stop_reason="run_cap",
        )
        done_sources.add(tid)
