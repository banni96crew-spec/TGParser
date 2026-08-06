from __future__ import annotations

from telegram_lead_discovery.source_discovery.active_chat import MIN_CLIENT_AUTHORS
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _bump_counter,
    _check_cancel,
    _commit_before_network,
    _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _ensure_utc,
    _FloodWaitControl,
    _SessionFatal,
    _utcnow,
    _WorkerContext,
)

# ruff: noqa: F403,F405
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *
from telegram_lead_discovery.source_discovery.worker_parts.history_evidence import (
    _classify_history_message,
    _history_evidence_record,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_progress import (
    _history_request,
    _save_history_progress,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _load_history_cursor,
    _run_history_scanned,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import _insert_evidence
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient,
    _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.truth_state import (
    _apply_source_truth,
    _may_persist_evidence,
    _source_meta_for_telegram_id,
    _username_for_telegram_id,
)
from telegram_lead_discovery.source_discovery.worker_parts.verification_terminal import (
    _apply_inaccessible_truth,
    _is_terminal_history_stop,
)


async def _resume_source_verification(
    ctx: _WorkerContext,
    query: DiscoveryRunQuery,
    *,
    max_pages: int | None = None,
) -> None:
    """Scan public history newest-to-oldest; ``max_pages`` enables fair scheduling."""
    if (
        query.state == "retry_wait"
        and query.available_at
        and _ensure_utc(query.available_at) > _utcnow()
    ):
        raise _FloodWaitControl(_ensure_utc(query.available_at), query)
    telegram_id = query.source_telegram_id
    if telegram_id is None:
        await _mark_query_terminal(query, "failed", error_code="missing_source")
        return
    query.state = "running"
    await ctx.session.flush()
    cursor = _load_history_cursor(query)
    scanned = int(cursor.get("scanned", 0))
    offset_id = int(cursor.get("offset_id", 0) or 0)
    noise_kept = int(cursor.get("noise_kept", 0))
    reference_at = ctx.run.reference_at or ctx.run.started_at
    if reference_at is None:
        raise RuntimeError("active_chat_reference_at_missing")
    active_payload = cursor.get("active_chat")
    accumulator = (
        ActiveChatAccumulator.from_cursor(active_payload)
        if isinstance(active_payload, dict)
        else ActiveChatAccumulator(reference_at=reference_at)
    )
    accumulator.assert_reference_at(reference_at)
    stop_reason: str | None = None
    result_count = int(query.result_count or 0)
    pages_done = 0
    source_meta = await _source_meta_for_telegram_id(ctx, telegram_id)
    username = source_meta.get("username") or await _username_for_telegram_id(ctx, telegram_id)

    while True:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        run_scanned = await _run_history_scanned(ctx)
        if scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE:
            stop_reason = "source_cap"
            break
        if run_scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN:
            stop_reason = "run_cap"
            break
        if all(active_chat_thresholds(accumulator.counters(), reference_at=reference_at).values()):
            stop_reason = "quality_reached"
            break

        page_limit = min(
            RUNTIME_CONFIG.HISTORY_PAGE_SIZE,
            RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE - scanned,
            RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN - run_scanned,
        )
        if page_limit <= 0:
            stop_reason = (
                "run_cap"
                if run_scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
                else "source_cap"
            )
            break
        request = _history_request(
            telegram_id=telegram_id,
            username=username,
            page_limit=page_limit,
            offset_id=offset_id,
        )
        page_msgs: list[Any] = []
        try:
            await _commit_before_network(ctx)
            async for dto in ctx.gateway.iter_history(request):
                page_msgs.append(dto)
                if len(page_msgs) >= page_limit:
                    break
            query.request_count += 1
        except GatewayFloodWait as exc:
            _save_history_progress(
                query,
                offset_id=offset_id,
                scanned=scanned,
                noise_kept=noise_kept,
                active_chat_cursor=accumulator.to_cursor(),
                stop_reason="flood_wait",
            )
            query.state = "retry_wait"
            query.available_at = exc.until
            query.error_code = "flood_wait"
            await ctx.session.flush()
            raise _FloodWaitControl(exc.until, query) from exc
        except GatewaySourceInaccessible:
            stop_reason = "inaccessible"
            await _mark_query_terminal(query, "failed", error_code="source_inaccessible")
            await _apply_inaccessible_truth(
                ctx, telegram_id=telegram_id, accumulator=accumulator, scanned=scanned
            )
            return
        except GatewayUnauthorized as exc:
            raise _SessionFatal("unauthorized") from exc
        except GatewayFrozen as exc:
            raise _SessionFatal("frozen") from exc
        except GatewayTransientError as exc:
            _save_history_progress(
                query,
                offset_id=offset_id,
                scanned=scanned,
                noise_kept=noise_kept,
                active_chat_cursor=accumulator.to_cursor(),
            )
            if await _handle_transient(ctx, query, "transient_error"):
                raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
            await _apply_inaccessible_truth(
                ctx, telegram_id=telegram_id, accumulator=accumulator, scanned=scanned
            )
            return
        except GatewayPermanentError:
            await _mark_query_terminal(query, "failed", error_code="permanent_error")
            await _bump_counter(ctx, "failed_queries", 1)
            await _apply_inaccessible_truth(
                ctx, telegram_id=telegram_id, accumulator=accumulator, scanned=scanned
            )
            return
        if not page_msgs:
            stop_reason = "history_exhausted"
            break
        scanned_this_page = 0
        for dto in page_msgs:
            published = _ensure_utc(dto.published_at)
            if published < _ensure_utc(reference_at) - timedelta(days=30):
                stop_reason = "window_complete"
                break
            scanned += 1
            scanned_this_page += 1
            offset_id = int(dto.telegram_message_id)
            classified = _classify_history_message(
                ctx,
                telegram_id=telegram_id,
                dto=dto,
                published_at=published,
            )
            evidence_author_needed = (
                classified.active_message.author_key not in accumulator.request_author_keys
                and len(accumulator.request_author_keys) < MIN_CLIENT_AUTHORS
            )
            client = accumulator.consume(
                classified.active_message,
                required_service_profiles=ctx.required_service_profiles,
            )
            if client and evidence_author_needed:
                if not await _may_persist_evidence(ctx, is_qualified=True):
                    raise _SessionFatal("evidence_capacity_invariant")
                persist = True
            elif client:
                persist = False
            elif (
                classified.active_message.hard_exclusion
                and noise_kept < RUNTIME_CONFIG.NOISE_EVIDENCE_CAP_PER_SOURCE
            ):
                noise_kept += 1
                persist = await _may_persist_evidence(ctx, is_qualified=False)
            else:
                persist = False

            if persist:
                identity = resolve_source_identity(
                    telegram_id=telegram_id,
                    username=username,
                    registry=ctx.registry,
                )
                record = _history_evidence_record(
                    run_id=ctx.run.id,
                    telegram_id=identity.canonical_telegram_id,
                    username=identity.username_normalized or username,
                    title=str(source_meta.get("title") or username or str(telegram_id)),
                    source_type=str(source_meta.get("source_type") or "megagroup"),
                    dto=dto,
                    excerpt=classified.excerpt,
                    normalized_hash=classified.normalized_hash,
                    detection=classified.detection,
                    query_ordinal=query.ordinal,
                    client=client,
                    author_key=classified.active_message.author_key,
                    author_kind=classified.active_message.author_kind,
                    hard_exclusion=classified.active_message.hard_exclusion,
                    exclusion_reason=classified.exclusion_reason,
                )
                await _insert_evidence(ctx, record)
                result_count += 1

            if all(
                active_chat_thresholds(accumulator.counters(), reference_at=reference_at).values()
            ):
                stop_reason = "quality_reached"
                break
            if scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE:
                stop_reason = "source_cap"
                break
            if (
                await _run_history_scanned(ctx) + scanned_this_page
                >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
            ):
                stop_reason = "run_cap"
                break
        if scanned_this_page:
            await _bump_counter(ctx, "history_scanned_total", scanned_this_page)
        pages_done += 1
        _save_history_progress(
            query,
            offset_id=offset_id,
            scanned=scanned,
            noise_kept=noise_kept,
            active_chat_cursor=accumulator.to_cursor(),
            stop_reason=stop_reason,
        )
        query.result_count = result_count
        await ctx.session.flush()
        if _is_terminal_history_stop(stop_reason):
            break
        if len(page_msgs) < page_limit:
            stop_reason = stop_reason or "history_exhausted"
            break
        if max_pages is not None and pages_done >= max_pages:
            query.state = "running"
            await ctx.session.flush()
            return
    if stop_reason is None:
        stop_reason = "history_exhausted"

    query.result_count = result_count
    _save_history_progress(
        query,
        offset_id=offset_id,
        scanned=scanned,
        noise_kept=noise_kept,
        active_chat_cursor=accumulator.to_cursor(),
        stop_reason=stop_reason,
    )
    await _apply_source_truth(
        ctx,
        telegram_id=telegram_id,
        counters=accumulator.counters(),
        scanned=scanned,
        stop_reason=stop_reason,
    )
    await _mark_query_terminal(query, "succeeded")
