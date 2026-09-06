"""Resolve operator_seed refs after SEARCH queries and before the 25-cap pool."""

from __future__ import annotations

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayPermanentError,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
    PublicSourceRef,
)
from telegram_lead_discovery.source_discovery.graph_edges import is_private_invite_ref
from telegram_lead_discovery.source_discovery.identity import (
    is_registry_suppressed,
    resolve_source_identity,
)
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _bump_counter,
    _check_cancel,
    _commit_before_network,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl,
    _SessionFatal,
    _utcnow,
    _WorkerContext,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _persist_operator_seed_pool,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import (
    _note_dismissed_suppressed,
    _note_presented_suppressed,
    _note_registry_suppressed,
)
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient,
    _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _dismissed_canonical_id,
    _presented_canonical_id,
)
from telegram_lead_discovery.storage.models import DiscoveryRunQuery


async def _skip_operator_seed(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    await _bump_counter(ctx, "operator_seed_skipped", 1)
    await _mark_query_terminal(query, "succeeded", error_code="operator_seed_skipped")


async def _execute_operator_seed_query(
    ctx: _WorkerContext, query: DiscoveryRunQuery
) -> None:
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()
    await _check_cancel(ctx)
    await _maybe_heartbeat(ctx)
    raw = (query.query_text or "").strip()
    if not raw or is_private_invite_ref(raw):
        await _skip_operator_seed(ctx, query)
        return
    try:
        username = normalize_username(raw)
    except InvalidUsernameError:
        await _skip_operator_seed(ctx, query)
        return
    try:
        await _commit_before_network(ctx)
        snap = await ctx.gateway.resolve_public_source(
            PublicSourceRef(schema_version=1, username_or_url=username)
        )
    except GatewayFloodWait as exc:
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewaySourceInaccessible:
        await _skip_operator_seed(ctx, query)
        return
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return
    except GatewayPermanentError:
        await _skip_operator_seed(ctx, query)
        return

    query.request_count += 1
    query.source_telegram_id = snap.telegram_id
    if (
        not snap.accessible
        or snap.source_type != "megagroup"
        or not snap.username
    ):
        await _skip_operator_seed(ctx, query)
        return

    identity = resolve_source_identity(
        telegram_id=snap.telegram_id,
        username=snap.username,
        registry=ctx.registry,
    )
    if is_registry_suppressed(identity, registry=ctx.registry):
        await _note_registry_suppressed(
            ctx, {identity.canonical_telegram_id or snap.telegram_id}
        )
        await _mark_query_terminal(query, "succeeded")
        return
    dismissed_id = _dismissed_canonical_id(
        ctx, telegram_id=snap.telegram_id, username=snap.username
    )
    if dismissed_id is not None:
        await _note_dismissed_suppressed(ctx, {dismissed_id})
        await _mark_query_terminal(query, "succeeded")
        return
    presented_id = _presented_canonical_id(
        ctx, telegram_id=snap.telegram_id, username=snap.username
    )
    if presented_id is not None:
        await _note_presented_suppressed(ctx, {presented_id})
        await _mark_query_terminal(query, "succeeded")
        return

    if all(item.telegram_id != snap.telegram_id for item in ctx.operator_seed_sources):
        ctx.operator_seed_sources.append(snap)
        await _persist_operator_seed_pool(ctx)
    query.result_count += 1
    await _mark_query_terminal(query, "succeeded")
