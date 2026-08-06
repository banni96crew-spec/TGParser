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


async def _finalize_unfinished(
    ctx: _WorkerContext,
    *,
    pool: list[dict[str, Any]],
    done_sources: set[int],
    suppressed_ids: set[int],
    stop_reason: str,
    query_state: str,
) -> None:
    """Create terminal inconclusive truth for every unfinished acquired source."""
    if stop_reason == "run_cap":
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
        reference_at = ctx.run.reference_at or ctx.run.started_at
        if reference_at is None:
            raise RuntimeError("active_chat_reference_at_missing")
        accumulator = ActiveChatAccumulator(reference_at=reference_at)
        if query is not None:
            cursor = _load_history_cursor(query)
            scanned = int(cursor.get("scanned", 0) or 0)
            active_payload = cursor.get("active_chat")
            if isinstance(active_payload, dict):
                accumulator = ActiveChatAccumulator.from_cursor(active_payload)
                accumulator.assert_reference_at(reference_at)
            if query.state not in _TERMINAL_VERIFICATION_STATES:
                _save_cursor(
                    query,
                    {
                        **cursor,
                        "stop_reason": stop_reason,
                    },
                )
                await _mark_query_terminal(query, query_state)
        await _apply_source_truth(
            ctx,
            telegram_id=tid,
            counters=accumulator.counters(),
            scanned=scanned,
            stop_reason=stop_reason,
        )
        done_sources.add(tid)


async def _finalize_unfinished_on_run_cap(
    ctx: _WorkerContext,
    *,
    pool: list[dict[str, Any]],
    done_sources: set[int],
    suppressed_ids: set[int],
) -> None:
    await _finalize_unfinished(
        ctx,
        pool=pool,
        done_sources=done_sources,
        suppressed_ids=suppressed_ids,
        stop_reason="run_cap",
        query_state="succeeded",
    )


async def _finalize_unfinished_on_cancel(
    ctx: _WorkerContext,
    *,
    pool: list[dict[str, Any]],
    done_sources: set[int],
    suppressed_ids: set[int],
) -> None:
    await _finalize_unfinished(
        ctx,
        pool=pool,
        done_sources=done_sources,
        suppressed_ids=suppressed_ids,
        stop_reason="cancelled",
        query_state="cancelled",
    )
