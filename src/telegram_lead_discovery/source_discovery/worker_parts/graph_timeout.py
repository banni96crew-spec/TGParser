"""Local skip of remaining graph stages after GatewayTimeout (SRC-056)."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select

from telegram_lead_discovery.source_discovery.graph_cursor import node_key
from telegram_lead_discovery.source_discovery.worker_parts.graph_stages import GRAPH_NODE_STAGES
from telegram_lead_discovery.source_discovery.worker_parts.graph_state import (
    _save_graph_cursor,
)
from telegram_lead_discovery.storage.models import SourceDiscoveryEvent

_ALL_STAGES = ("resolve", *GRAPH_NODE_STAGES)


def _empty_stage_payload(stage: str) -> Any:
    if stage == "message_sample_100":
        return {
            "schema_version": 1,
            "edges": [],
            "posts_persisted": 0,
        }
    return []


async def skip_remaining_graph_stages(
    ctx: Any, *, count_timeout: bool = True
) -> None:
    node = ctx.current_node
    if node is None:
        return
    key = node_key(node)
    completed = ctx.completed_stages.setdefault(key, set())
    results = ctx.stage_results.setdefault(key, {})
    skipped = False
    for stage in _ALL_STAGES:
        if stage in completed:
            continue
        skipped = True
        if results.get(stage) is None:
            results[stage] = _empty_stage_payload(stage)
        completed.add(stage)
    if skipped:
        if count_timeout:
            ctx.budget.node_timeout_total += 1
            await _persist_node_timeout_event(ctx, key=key, node=node)
        # #region agent log
        import json as _json, time as _time
        from pathlib import Path as _Path
        try:
            with _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log").open(
                "a", encoding="utf-8"
            ) as _f:
                _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H4","location":"graph_timeout.py:skip_remaining_graph_stages","message":"node_skipped","data":{"key":key,"timeout_total":ctx.budget.node_timeout_total,"run_id":ctx.run.id},"timestamp":int(_time.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
    ctx.current_node = None
    _save_graph_cursor(ctx)
    await ctx.session.commit()


async def _persist_node_timeout_event(ctx: Any, *, key: str, node: Any) -> None:
    payload = "|".join(
        ("node_timeout", str(ctx.run.id), key, str(node.depth))
    )
    event_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    existing = await ctx.session.execute(
        select(SourceDiscoveryEvent.id).where(SourceDiscoveryEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        return
    ctx.session.add(
        SourceDiscoveryEvent(
            event_id=event_id,
            run_id=ctx.run.id,
            source_id=node.seed_source_id,
            method="timeout",
            parent_source_id=ctx.parent_by_telegram_id.get(node.seed_telegram_id),
            raw_reference=node.username or str(node.seed_telegram_id),
            normalized_reference=key,
            outcome="node_timeout",
            depth=node.depth,
        )
    )


__all__ = ["skip_remaining_graph_stages"]
