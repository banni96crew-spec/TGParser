"""Terminal history-verification helpers."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext
from telegram_lead_discovery.source_discovery.worker_parts.truth_state import _apply_source_truth

_TERMINAL_HISTORY_STOPS = frozenset(
    {"quality_reached", "window_complete", "source_cap", "run_cap", "history_exhausted"}
)


def _is_terminal_history_stop(value: str | None) -> bool:
    return value in _TERMINAL_HISTORY_STOPS


async def _apply_inaccessible_truth(
    ctx: _WorkerContext,
    *,
    telegram_id: int,
    accumulator: Any,
    scanned: int,
) -> None:
    await _apply_source_truth(
        ctx,
        telegram_id=telegram_id,
        counters=accumulator.counters(),
        scanned=scanned,
        stop_reason="inaccessible",
    )


__all__ = ["_apply_inaccessible_truth", "_is_terminal_history_stop"]
