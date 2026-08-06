from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl,
    _SessionFatal,
    _WorkerContext,
    _ensure_utc,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _check_cancel,
    _commit_before_network,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import (
    _note_dismissed_suppressed,
    _note_presented_suppressed,
    _note_registry_suppressed,
    _upsert_opportunity,
)
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient,
    _mark_query_terminal,
    _parked_queries,
    _restore_linked_parents,
    _source_ids_with_query_kind,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import (
    _channel_telegram_ids,
    _next_ordinal,
)


async def _phase_linked_discussions(ctx: _WorkerContext) -> None:
    ctx.run.phase = "F"
    await ctx.session.flush()
    await _restore_linked_parents(ctx)
    known = await _source_ids_with_query_kind(ctx, "linked_discussion")
    channel_ids = await _channel_telegram_ids(ctx)
    next_ordinal = await _next_ordinal(ctx)

    for query in await _parked_queries(ctx, "linked_discussion"):
        await _resume_linked_query(ctx, query)

    for telegram_id in channel_ids:
        if telegram_id in known:
            continue
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        query = DiscoveryRunQuery(
            run_id=ctx.run.id,
            ordinal=next_ordinal,
            query_kind="linked_discussion",
            query_text="",
            source_telegram_id=telegram_id,
            state="running",
            started_at=_utcnow(),
        )
        next_ordinal += 1
        ctx.session.add(query)
        await ctx.session.flush()
        await _resume_linked_query(ctx, query)


async def _resume_linked_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    telegram_id = query.source_telegram_id
    if telegram_id is None:
        await _mark_query_terminal(query, "failed", error_code="missing_source")
        return
    if (
        query.state == "retry_wait"
        and query.available_at
        and _ensure_utc(query.available_at) > _utcnow()
    ):
        raise _FloodWaitControl(_ensure_utc(query.available_at), query)
    query.state = "running"
    await ctx.session.flush()
    try:
        await _commit_before_network(ctx)
        discussion = await ctx.gateway.get_linked_discussion(
            SourceRef(schema_version=1, source_id=0, telegram_id=telegram_id)
        )
        query.request_count += 1
    except GatewayFloodWait as exc:
        query.state = "retry_wait"
        query.available_at = exc.until
        query.error_code = "flood_wait"
        await ctx.session.flush()
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewaySourceInaccessible:
        await _mark_query_terminal(query, "failed", error_code="source_inaccessible")
        return
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return

    if (
        discussion is None
        or not discussion.accessible
        or not discussion.username
        or discussion.source_type not in ("megagroup", "group")
    ):
        await _mark_query_terminal(query, "succeeded", error_code="no_public_linked")
        return

    ctx.linked_parents[discussion.telegram_id] = telegram_id
    identity = resolve_source_identity(
        telegram_id=discussion.telegram_id,
        username=discussion.username,
        registry=ctx.registry,
    )
    if is_registry_suppressed(identity, registry=ctx.registry):
        await _note_registry_suppressed(ctx, {identity.canonical_telegram_id})
        await _mark_query_terminal(query, "succeeded", error_code="registry_suppressed")
        return
    dismissed_match = resolve_dismissed_identity(
        telegram_id=identity.canonical_telegram_id,
        username=identity.username_normalized or discussion.username,
        dismissed=ctx.dismissed,
    )
    if dismissed_match is not None:
        await _note_dismissed_suppressed(ctx, {dismissed_match.canonical_telegram_id})
        await _mark_query_terminal(query, "succeeded", error_code="dismissed_suppressed")
        return
    presented_match = resolve_presented_identity(
        telegram_id=identity.canonical_telegram_id,
        username=identity.username_normalized or discussion.username,
        presented=ctx.presented,
    )
    if presented_match is not None:
        await _note_presented_suppressed(ctx, {presented_match.canonical_telegram_id})
        await _mark_query_terminal(query, "succeeded", error_code="presented_suppressed")
        return
    snap = linked_discussion_opportunity(
        run_id=ctx.run.id,
        parent_telegram_id=telegram_id,
        discussion=discussion,
        scored_at=_utcnow(),
        registry_source_id=identity.registry_source_id,
    )
    await _upsert_opportunity(ctx, snap)
    query.result_count = 1
    await _mark_query_terminal(query, "succeeded")
