from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _FloodWaitControl, _SessionFatal, _WorkerContext, _ensure_utc, _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import (
    _bump_counter, _check_cancel, _commit_before_network, _maybe_heartbeat,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import (
    _load_history_cursor, _run_history_scanned,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_progress import (
    _history_request, _save_history_progress,
)
from telegram_lead_discovery.source_discovery.worker_parts.persistence import _insert_evidence
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _handle_transient, _mark_query_terminal,
)
from telegram_lead_discovery.source_discovery.worker_parts.truth_state import (
    _apply_source_truth, _may_persist_evidence, _source_meta_for_telegram_id,
    _username_for_telegram_id,
)

async def _resume_source_verification(
    ctx: _WorkerContext,
    query: DiscoveryRunQuery,
    *,
    max_pages: int | None = None,
) -> None:
    """Bounded public history scan newest→older (SRC-024 / D-068).

    ``max_pages`` limits pages for fair waterfill scheduling (technical policy).
    ``None`` drains until a terminal stop (legacy full-source scan).
    """
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
    distinct_hashes: set[str] = set(cursor.get("distinct_hashes", []) or [])
    noise_kept = int(cursor.get("noise_kept", 0))
    now = _utcnow()
    window_start = quality_window_start(now, days=RUNTIME_CONFIG.QUALITY_WINDOW_DAYS)
    stop_reason: str | None = None
    window_complete = False
    hit_source_cap = False
    hit_run_cap = False
    result_count = int(query.result_count or 0)
    pages_done = 0
    source_meta = await _source_meta_for_telegram_id(ctx, telegram_id)
    username = source_meta.get("username") or await _username_for_telegram_id(ctx, telegram_id)

    while True:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        run_scanned = await _run_history_scanned(ctx)
        if scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE:
            hit_source_cap = True
            stop_reason = "source_cap"
            break
        if run_scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN:
            hit_run_cap = True
            stop_reason = "run_cap"
            break
        if len(distinct_hashes) >= 7:
            stop_reason = "quality_reached"
            break

        page_limit = min(
            RUNTIME_CONFIG.HISTORY_PAGE_SIZE,
            RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE - scanned,
            RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN - run_scanned,
        )
        if page_limit <= 0:
            hit_run_cap = run_scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
            hit_source_cap = scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE
            stop_reason = "run_cap" if hit_run_cap else "source_cap"
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
                distinct_hashes=distinct_hashes,
                noise_kept=noise_kept,
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
            await _apply_source_truth(
                ctx,
                telegram_id=telegram_id,
                distinct_count=len(distinct_hashes),
                scanned=scanned,
                window_complete=False,
                hit_source_cap=False,
                hit_run_cap=False,
                stop_reason=stop_reason,
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
                distinct_hashes=distinct_hashes,
                noise_kept=noise_kept,
            )
            if await _handle_transient(ctx, query, "transient_error"):
                raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
            return
        except GatewayPermanentError:
            await _mark_query_terminal(query, "failed", error_code="permanent_error")
            await _bump_counter(ctx, "failed_queries", 1)
            return
        if not page_msgs:
            window_complete = True
            stop_reason = "source_exhausted"
            break
        scanned_this_page = 0
        for dto in page_msgs:
            published = _ensure_utc(dto.published_at)
            if published < window_start:
                window_complete = True
                stop_reason = "window_reached"
                # Do not count messages past the 14d boundary toward caps.
                break
            scanned += 1
            scanned_this_page += 1
            offset_id = int(dto.telegram_message_id)
            excerpt, normalized_hash, detection = qualify_excerpt_text(
                dto.text or "",
                detect_fn=seed_catalog_detect,
            )
            client = is_client_request(
                category=detection.category,
                service_profiles=detection.service_profiles,
                hard_exclusion=detection.hard_exclusion,
            )
            persist = False
            if client and is_within_quality_window(published, now=now):
                if normalized_hash not in distinct_hashes:
                    distinct_hashes.add(normalized_hash)
                    persist = True
            elif (
                detection.hard_exclusion
                and noise_kept < RUNTIME_CONFIG.NOISE_EVIDENCE_CAP_PER_SOURCE
            ):
                noise_kept += 1
                persist = True

            if persist and await _may_persist_evidence(ctx, is_qualified=client):
                identity = resolve_source_identity(
                    telegram_id=telegram_id,
                    username=username,
                    registry=ctx.registry,
                )
                record = EvidenceRecord(
                    run_id=ctx.run.id,
                    source_telegram_id=identity.canonical_telegram_id,
                    source_username=identity.username_normalized or username,
                    source_title=str(source_meta.get("title") or username or str(telegram_id)),
                    source_type=str(source_meta.get("source_type") or "megagroup"),
                    telegram_message_id=int(dto.telegram_message_id),
                    published_at=published,
                    permalink=dto.permalink,
                    excerpt=excerpt,
                    normalized_hash=normalized_hash,
                    matched_query_ordinals=(query.ordinal,),
                    discovery_channels=("source_verification",),
                    detection_category=detection.category,
                    is_qualified=client,
                    hard_exclusion=detection.hard_exclusion,
                    hard_exclusion_rule_id=detection.hard_exclusion_rule_id,
                    service_profiles=detection.service_profiles,
                    rule_set_checksum=detection.rule_set_checksum,
                    matched_rule_ids=tuple(m.stable_rule_id for m in detection.matched_rules),
                )
                await _insert_evidence(ctx, record)
                result_count += 1

            if len(distinct_hashes) >= 7:
                stop_reason = "quality_reached"
                break
            if scanned >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_SOURCE:
                hit_source_cap = True
                stop_reason = "source_cap"
                break
            if (
                await _run_history_scanned(ctx) + scanned_this_page
                >= RUNTIME_CONFIG.HISTORY_SCAN_CAP_PER_RUN
            ):
                hit_run_cap = True
                stop_reason = "run_cap"
                break
        if scanned_this_page:
            await _bump_counter(ctx, "history_scanned_total", scanned_this_page)
        pages_done += 1
        _save_history_progress(
            query,
            offset_id=offset_id,
            scanned=scanned,
            distinct_hashes=distinct_hashes,
            noise_kept=noise_kept,
            stop_reason=stop_reason,
        )
        query.result_count = result_count
        await ctx.session.flush()
        if stop_reason in {
            "quality_reached",
            "window_reached",
            "source_cap",
            "run_cap",
            "source_exhausted",
        }:
            if stop_reason == "run_cap":
                hit_run_cap = True
            if stop_reason == "source_cap":
                hit_source_cap = True
            if stop_reason == "window_reached":
                window_complete = True
            break
        if len(page_msgs) < page_limit:
            window_complete = True
            stop_reason = stop_reason or "source_exhausted"
            break
        if max_pages is not None and pages_done >= max_pages:
            await _apply_source_truth(
                ctx,
                telegram_id=telegram_id,
                distinct_count=len(distinct_hashes),
                scanned=scanned,
                window_complete=False,
                hit_source_cap=False,
                hit_run_cap=False,
                stop_reason=None,
            )
            query.state = "running"
            await ctx.session.flush()
            return
    if stop_reason is None:
        window_complete = True
        stop_reason = "source_exhausted"

    query.result_count = result_count
    _save_history_progress(
        query,
        offset_id=offset_id,
        scanned=scanned,
        distinct_hashes=distinct_hashes,
        noise_kept=noise_kept,
        stop_reason=stop_reason,
    )
    await _apply_source_truth(
        ctx,
        telegram_id=telegram_id,
        distinct_count=len(distinct_hashes),
        scanned=scanned,
        window_complete=window_complete,
        hit_source_cap=hit_source_cap,
        hit_run_cap=hit_run_cap,
        stop_reason=stop_reason,
    )
    await _mark_query_terminal(query, "succeeded")
