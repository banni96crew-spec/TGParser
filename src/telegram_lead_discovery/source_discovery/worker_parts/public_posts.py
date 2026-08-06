from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl,
    _SessionFatal,
    _WorkerContext,
    _cursor_payload,
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
from telegram_lead_discovery.source_discovery.worker_parts.persistence import _persist_hits
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient,
    _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import _evidence_count


async def _execute_public_posts_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    payload = _cursor_payload(query.cursor_json)
    pages_done = int(payload.get("pages_done", 0))
    cursor = _search_cursor_from_payload(payload)
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()

    await _check_cancel(ctx)
    try:
        await _commit_before_network(ctx)
        quota = await ctx.gateway.check_public_post_search_quota(query.query_text)
    except GatewayFloodWait as exc:
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewayPremiumRequired:
        ctx.run.quota_snapshot_json = json.dumps(
            {
                "free_slot_available": False,
                "premium_required": True,
                "stars_amount": 0,
            },
            ensure_ascii=False,
        )
        await _mark_query_terminal(query, "quota_skipped", error_code="premium_required")
        await _bump_counter(ctx, "quota_skipped_queries", 1)
        return
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return

    ctx.run.quota_snapshot_json = json.dumps(
        {
            "free_slot_available": quota.free_slot_available,
            "premium_required": quota.premium_required,
            "stars_amount": quota.stars_amount,
        },
        ensure_ascii=False,
    )

    if quota.premium_required or (not quota.free_slot_available and quota.stars_amount > 0):
        error = "premium_required" if quota.premium_required else "quota_exhausted"
        if not quota.free_slot_available:
            ctx.public_posts_quota_exhausted = True
        await _mark_query_terminal(query, "quota_skipped", error_code=error)
        await _bump_counter(ctx, "quota_skipped_queries", 1)
        return
    if not quota.free_slot_available:
        ctx.public_posts_quota_exhausted = True
        await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
        await _bump_counter(ctx, "quota_skipped_queries", 1)
        return

    while pages_done < RUNTIME_CONFIG.GLOBAL_MAX_PAGES:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if await _evidence_count(ctx) >= RUNTIME_CONFIG.MAX_EVIDENCE_PER_RUN:
            await _mark_query_terminal(query, "budget_skipped", error_code="evidence_cap")
            await _bump_counter(ctx, "budget_skipped", 1)
            return

        request = PublicPostSearchRequest(
            schema_version=1,
            query=query.query_text,
            limit=RUNTIME_CONFIG.GLOBAL_PAGE_SIZE,
            cursor=cursor,
        )
        try:
            await _commit_before_network(ctx)
            page = await ctx.gateway.search_public_posts(request)
        except GatewayFloodWait as exc:
            _save_cursor(
                query,
                {"token": cursor.token if cursor else "", "pages_done": pages_done},
            )
            raise _FloodWaitControl(exc.until, query) from exc
        except GatewayPremiumRequired:
            ctx.public_posts_quota_exhausted = True
            ctx.run.quota_snapshot_json = json.dumps(
                {
                    "free_slot_available": False,
                    "premium_required": True,
                    "stars_amount": 0,
                    "eligibility": "confirmed_on_search",
                },
                ensure_ascii=False,
            )
            await _mark_query_terminal(query, "quota_skipped", error_code="premium_required")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            return
        except GatewaySearchQuotaExhausted:
            ctx.public_posts_quota_exhausted = True
            await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            return
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
        annotated = [
            AnnotatedSearchHit(
                hit=hit,
                query_ordinal=query.ordinal,
                discovery_channel="public_posts",
            )
            for hit in page.hits
        ]
        await _persist_hits(ctx, annotated)
        query.result_count += len(page.hits)
        pages_done += 1
        next_token = page.next_cursor.token if page.next_cursor else ""
        _save_cursor(query, {"token": next_token, "pages_done": pages_done})
        await ctx.session.flush()
        cursor = page.next_cursor
        if cursor is None or not page.hits:
            break

    await _mark_query_terminal(query, "succeeded")
