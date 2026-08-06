from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl,
    _SessionFatal,
    _WorkerContext,
    _cursor_payload,
    _ensure_utc,
    _save_cursor,
    _search_cursor_from_payload,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _bump_counter,
    _check_cancel,
    _commit_before_network,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _persist_directory_pool,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import _persist_hits
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient,
    _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import _evidence_count


async def _run_seed_queries(ctx: _WorkerContext) -> None:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind.in_(("global_message", "directory", "public_posts")),
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
    )
    queries = list(result.scalars().all())
    for query in queries:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if query.state in (
            "succeeded",
            "failed",
            "cancelled",
            "quota_skipped",
            "budget_skipped",
        ):
            continue
        if query.state == "retry_wait" and query.available_at is not None:
            if _ensure_utc(query.available_at) > _utcnow():
                # Still waiting — re-park job until query.available_at.
                raise _FloodWaitControl(_ensure_utc(query.available_at), query)
            query.state = "running"

        if (
            query.query_kind == "public_posts"
            and ctx.public_posts_quota_exhausted
            and query.state in ("queued", "running", "retry_wait")
        ):
            await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            continue

        if query.query_kind == "global_message":
            ctx.run.phase = "B"
            await _execute_global_query(ctx, query)
        elif query.query_kind == "directory":
            ctx.run.phase = "C"
            await _execute_directory_query(ctx, query)
        elif query.query_kind == "public_posts":
            ctx.run.phase = "D"
            await _execute_public_posts_query(ctx, query)
        await ctx.session.flush()


async def _execute_global_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    payload = _cursor_payload(query.cursor_json)
    pages_done = int(payload.get("pages_done", 0))
    cursor = _search_cursor_from_payload(payload)
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()

    groups_only = query.scope == "groups"
    broadcasts_only = query.scope == "channels"

    while pages_done < RUNTIME_CONFIG.GLOBAL_MAX_PAGES:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if await _evidence_count(ctx) >= RUNTIME_CONFIG.MAX_EVIDENCE_PER_RUN:
            await _mark_query_terminal(query, "budget_skipped", error_code="evidence_cap")
            await _bump_counter(ctx, "budget_skipped", 1)
            return

        request = GlobalSearchRequest(
            schema_version=1,
            query=query.query_text,
            groups_only=groups_only,
            broadcasts_only=broadcasts_only,
            limit=RUNTIME_CONFIG.GLOBAL_PAGE_SIZE,
            cursor=cursor,
        )
        try:
            await _commit_before_network(ctx)
            page = await ctx.gateway.search_global(request)
        except GatewayFloodWait as exc:
            _save_cursor(
                query,
                {"token": cursor.token if cursor else "", "pages_done": pages_done},
            )
            raise _FloodWaitControl(exc.until, query) from exc
        except GatewayUnauthorized as exc:
            raise _SessionFatal("unauthorized") from exc
        except GatewayFrozen as exc:
            raise _SessionFatal("frozen") from exc
        except GatewayInvalidSearchQuery:
            await _mark_query_terminal(query, "failed", error_code="invalid_query")
            await _bump_counter(ctx, "failed_queries", 1)
            return
        except GatewayTransientError as exc:
            if await _handle_transient(ctx, query, "transient_error"):
                raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
            return
        except GatewayPermanentError:
            await _mark_query_terminal(query, "failed", error_code="permanent_error")
            await _bump_counter(ctx, "failed_queries", 1)
            return

        query.request_count += 1
        # Clear transient streak after a successful page.
        payload = _cursor_payload(query.cursor_json)
        payload.pop("transient_attempts", None)

        annotated = [
            AnnotatedSearchHit(
                hit=hit,
                query_ordinal=query.ordinal,
                discovery_channel="global_message",
            )
            for hit in page.hits
        ]
        await _persist_hits(ctx, annotated)
        query.result_count += len(page.hits)
        pages_done += 1
        next_token = page.next_cursor.token if page.next_cursor else ""
        _save_cursor(
            query,
            {"token": next_token, "pages_done": pages_done},
        )
        await ctx.session.flush()
        cursor = page.next_cursor
        if cursor is None or not page.hits:
            break

    await _mark_query_terminal(query, "succeeded")


async def _execute_directory_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()
    await _check_cancel(ctx)
    request = DirectorySearchRequest(
        schema_version=1,
        query=query.query_text,
        limit=RUNTIME_CONFIG.DIRECTORY_PEER_LIMIT,
    )
    try:
        await _commit_before_network(ctx)
        peers = await ctx.gateway.search_public_sources(request)
    except GatewayFloodWait as exc:
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayInvalidSearchQuery:
        await _mark_query_terminal(query, "failed", error_code="invalid_query")
        await _bump_counter(ctx, "failed_queries", 1)
        return
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return
    except GatewayPermanentError:
        await _mark_query_terminal(query, "failed", error_code="permanent_error")
        await _bump_counter(ctx, "failed_queries", 1)
        return

    query.request_count += 1
    accepted = [
        p
        for p in peers
        if p.accessible and p.source_type in ("channel", "megagroup", "group") and p.username
    ]
    ctx.directory_sources.extend(accepted)
    await _persist_directory_pool(ctx)
    query.result_count += len(accepted)
    await _mark_query_terminal(query, "succeeded")


from telegram_lead_discovery.source_discovery.worker_parts.public_posts import (
    _execute_public_posts_query,
)
