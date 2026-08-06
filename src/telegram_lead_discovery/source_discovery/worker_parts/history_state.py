from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _cursor_payload,
    _loads_counters,
    _utcnow,
)


async def _verification_scanned_by_source(ctx: _WorkerContext) -> dict[int, int]:
    """Per-source scanned counts from verification query cursors (fair waterfill)."""
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
        )
    )
    out: dict[int, int] = {}
    for row in result.scalars():
        if row.source_telegram_id is None:
            continue
        cursor = _load_history_cursor(row)
        out[int(row.source_telegram_id)] = int(cursor.get("scanned", 0) or 0)
    return out


async def _get_or_create_verification_query(
    ctx: _WorkerContext,
    *,
    telegram_id: int,
    next_ordinal: int,
) -> DiscoveryRunQuery:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
            DiscoveryRunQuery.source_telegram_id == telegram_id,
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    query = DiscoveryRunQuery(
        run_id=ctx.run.id,
        ordinal=next_ordinal,
        query_kind="source_verification",
        query_text=RUNTIME_CONFIG.HISTORY_SCAN_QUERY_TEXT,
        source_telegram_id=telegram_id,
        state="running",
        started_at=_utcnow(),
    )
    ctx.session.add(query)
    await ctx.session.flush()
    return query


async def _run_history_scanned(ctx: _WorkerContext) -> int:
    counters = _loads_counters(ctx.run.counters_json)
    return int(counters.get("history_scanned_total", 0))


def _load_history_cursor(query: DiscoveryRunQuery) -> dict[str, Any]:
    raw = query.cursor_json or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_run_cursor(ctx: _WorkerContext) -> dict[str, Any]:
    return _cursor_payload(ctx.run.cursor_json)


async def _persist_directory_pool(ctx: _WorkerContext) -> None:
    payload = _load_run_cursor(ctx)
    seen: dict[int, dict[str, Any]] = {}
    for item in payload.get("directory_pool") or []:
        if isinstance(item, dict) and "telegram_id" in item:
            seen[int(item["telegram_id"])] = item
    for snap in ctx.directory_sources:
        seen[snap.telegram_id] = {
            "telegram_id": snap.telegram_id,
            "username": snap.username,
            "title": snap.title,
            "source_type": snap.source_type,
            "public_url": snap.public_url,
        }
    payload["directory_pool"] = list(seen.values())
    ctx.run.cursor_json = json.dumps(payload, ensure_ascii=False)
    await ctx.session.flush()


async def _restore_directory_pool(ctx: _WorkerContext) -> None:
    if ctx.directory_sources:
        return
    payload = _load_run_cursor(ctx)
    restored: list[SourceSnapshot] = []
    for item in payload.get("directory_pool") or []:
        if not isinstance(item, dict):
            continue
        tid = int(item["telegram_id"])
        restored.append(
            SourceSnapshot(
                schema_version=1,
                telegram_id=tid,
                username=item.get("username") or "",
                title=str(item.get("title") or item.get("username") or tid),
                source_type=str(item.get("source_type") or "megagroup"),  # type: ignore[arg-type]
                public_url=item.get("public_url"),
                accessible=True,
            )
        )
    ctx.directory_sources = restored
