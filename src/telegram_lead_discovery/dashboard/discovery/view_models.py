"""View-model construction for keyword-discovery pages."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy import select

from telegram_lead_discovery.source_discovery.keyword_search import (
    POOL_EXHAUSTED_REASON_CODES,
)
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)

_TERMINAL_QUERY_STATES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "quota_skipped",
        "budget_skipped",
    }
)
_ACTIVE_RUN_STATES = frozenset(
    {"queued", "running", "retry_wait_flood", "cancelling"}
)
_SEED_QUERY_KINDS = frozenset({"global_message", "directory", "public_posts"})
# Default queue: review + promising (plan moderate/strong aliases). weak is opt-in.
_DEFAULT_BANDS = frozenset({"review", "promising"})
_BAND_FILTER_DEFAULT = "all"  # UI-025 / D-068: show all truth buckets by default
_POOL_REASON_BY_CODE = {v: k for k, v in POOL_EXHAUSTED_REASON_CODES.items()}
_FUNNEL_KEYS = (
    "acquired_total",
    "canonicalized_total",
    "registry_suppressed",
    "dismissed_suppressed",
    "cooldown_suppressed",
    "presented_suppressed",
    "suppressed_total",
    "qualified_total",
    "presented_total",
    "novel_presented_total",
    "duplicate_in_run",
)
_TRUTH_LABELS = {
    "quality": "Качественные",
    "near": "Почти (1–6)",
    "inconclusive": "Недоказанные",
    "rejected": "Отклонённые",
}


async def _quota_summary(request: Request) -> dict[str, Any]:
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None or not hasattr(gateway, "check_public_post_search_quota"):
        return {
            "available": False,
            "free_slot_available": None,
            "premium_required": None,
            "label": "квота недоступна (нет gateway)",
        }
    try:
        quota = await gateway.check_public_post_search_quota("нужен разработчик сайта")
        if quota.premium_required:
            label = "требуется Premium (Stars не используются)"
        elif quota.free_slot_available:
            # Check alone is inconclusive — SearchPosts may still raise Premium.
            label = "квота reported free; eligibility confirms on search"
        else:
            label = "бесплатный слот исчерпан / недоступен"
        return {
            "available": True,
            "free_slot_available": quota.free_slot_available,
            "premium_required": quota.premium_required,
            "label": label,
        }
    except Exception:  # noqa: BLE001 — UI must not expose gateway internals
        return {
            "available": False,
            "free_slot_available": None,
            "premium_required": None,
            "label": "квота временно недоступна",
        }


def _loads_json_obj(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _run_view(
    run: DiscoveryRun,
    *,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counters = _loads_json_obj(run.counters_json, {})
    if not isinstance(counters, dict):
        counters = {}
    prog = progress or {}
    pool_exhausted = bool(int(counters.get("pool_exhausted") or 0))
    reason_code = counters.get("pool_exhausted_reason_code")
    pool_reason = None
    if isinstance(reason_code, int):
        pool_reason = _POOL_REASON_BY_CODE.get(reason_code, f"code_{reason_code}")
    novelty_bp = int(counters.get("novelty_ratio_bp") or 0)
    funnel = {key: int(counters.get(key) or 0) for key in _FUNNEL_KEYS}
    # D-069: cooldown_suppressed is alias of presented_suppressed (unique peers).
    presented_unique = max(
        funnel["presented_suppressed"], funnel["cooldown_suppressed"]
    )
    funnel["presented_suppressed"] = presented_unique
    funnel["cooldown_suppressed"] = presented_unique
    # Aggregate suppressed for UI-020 "suppressed" line when total missing.
    if funnel["suppressed_total"] == 0:
        funnel["suppressed_total"] = (
            funnel["registry_suppressed"]
            + funnel["dismissed_suppressed"]
            + funnel["presented_suppressed"]
            + funnel["duplicate_in_run"]
        )
    return {
        "id": run.id,
        "state": run.state,
        "phase": run.phase,
        "version": run.version,
        "search_mode": run.search_mode,
        "last_error_code": run.last_error_code,
        "counters": counters,
        "funnel": funnel,
        "pool_exhausted": pool_exhausted,
        "pool_exhausted_reason": pool_reason,
        "novelty_ratio": novelty_bp / 10000.0,
        "novelty_ratio_bp": novelty_bp,
        "novelty_ratio_pct": f"{novelty_bp / 100:.2f}%",
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "queries_total": int(prog.get("queries_total", 0)),
        "queries_done": int(prog.get("queries_done", 0)),
        "progress_pct": int(prog.get("progress_pct", 0)),
        "seed_hits": int(prog.get("seed_hits", 0)),
        "verified_sources": int(prog.get("verified_sources", 0)),
        "flood_wait_until": prog.get("flood_wait_until"),
        "gate_status": counters.get("gate_status", "fail"),
        "quality_sources": int(counters.get("quality_sources") or 0),
        "near_sources": int(counters.get("near_sources") or 0),
        "inconclusive_sources": int(counters.get("inconclusive_sources") or 0),
        "rejected_sources": int(counters.get("rejected_sources") or 0),
        "globally_distinct_client_requests": int(
            counters.get("globally_distinct_client_requests") or 0
        ),
        "history_scanned_total": int(counters.get("history_scanned_total") or 0),
        "is_active": bool(prog.get("is_active", run.state in _ACTIVE_RUN_STATES)),
        "is_loading": run.state in _ACTIVE_RUN_STATES,
        "is_degraded": run.state == "retry_wait_flood" or bool(run.last_error_code),
        "is_error": run.state == "failed",
        "is_empty": (
            run.state not in _ACTIVE_RUN_STATES
            and int(counters.get("presented_total") or 0) == 0
            and int(counters.get("unique_sources") or 0) == 0
        ),
    }


async def _run_progress(session: Any, run: DiscoveryRun) -> dict[str, Any]:
    queries = (
        await session.execute(
            select(DiscoveryRunQuery).where(DiscoveryRunQuery.run_id == run.id)
        )
    ).scalars().all()
    total = len(queries)
    done = sum(1 for q in queries if q.state in _TERMINAL_QUERY_STATES)
    seed_hits = sum(
        int(q.result_count or 0) for q in queries if q.query_kind in _SEED_QUERY_KINDS
    )
    verified = sum(
        1
        for q in queries
        if q.query_kind == "source_verification" and q.state == "succeeded"
    )
    flood_until = None
    for q in queries:
        if q.state == "retry_wait" and q.available_at is not None:
            if flood_until is None or q.available_at > flood_until:
                flood_until = q.available_at
    return {
        "queries_total": total,
        "queries_done": done,
        "progress_pct": int(100 * done / total) if total else 0,
        "seed_hits": seed_hits,
        "verified_sources": verified,
        "flood_wait_until": flood_until,
        "is_active": run.state in _ACTIVE_RUN_STATES,
    }


def _rank_reason(view: dict[str, Any]) -> str:
    components = view.get("score_components") or {}
    ordered = (
        "qualified",
        "regularity",
        "ecommerce",
        "recency",
        "noise_penalty",
    )
    parts = [f"{key}={components.get(key, 0)}" for key in ordered]
    eligibility = components.get("eligibility_reasons") or components.get("reason_codes") or []
    if isinstance(eligibility, list) and eligibility:
        parts.append("reasons=" + ",".join(str(r) for r in eligibility))
    return (
        f"Выше других по score {view.get('score', 0)} "
        f"(band={view.get('band', 'weak')}; {', '.join(parts)})"
    )


def _eligibility_reasons(components: dict[str, Any]) -> list[str]:
    raw = components.get("eligibility_reasons") or components.get("reason_codes") or []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _normalize_band_filter(band: str | None) -> str:
    """Map query param to filter mode. Missing/empty → all truth buckets (UI-025)."""
    if band is None or band == "" or band == "default":
        return _BAND_FILTER_DEFAULT
    if band == "all":
        return "all"
    if band in ("promising", "review", "weak"):
        return band
    return _BAND_FILTER_DEFAULT


def _truth_label(status: str | None) -> str:
    return _TRUTH_LABELS.get(status or "inconclusive", status or "inconclusive")


def _sampling_label(sample_message_count: int) -> str:
    if sample_message_count <= 0:
        return "Недостаточный sample (0 сообщений)"
    return f"Sample: {sample_message_count} сообщений"


def _opportunity_view(
    row: SourceOpportunitySnapshot,
    *,
    lifecycle_state: str | None = None,
    aliases: list[str] | None = None,
    suppress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = _loads_json_obj(row.score_components_json, {})
    channels = _loads_json_obj(row.discovery_channels_json, [])
    if not isinstance(components, dict):
        components = {}
    if not isinstance(channels, list):
        channels = []
    existing = row.source_id is not None
    lifecycle = lifecycle_state or ("existing" if existing else "new")
    noise = components.get("noise_penalty", row.excluded_count)
    truth_status = getattr(row, "truth_status", None) or "inconclusive"
    identity = {
        "telegram_id": row.source_telegram_id,
        "username": row.username,
        "title": row.title,
        "source_type": row.source_type,
        "public_url": row.public_url,
        "canonical_key": (
            f"peer:{row.source_telegram_id}"
            if row.source_telegram_id is not None
            else (
                f"username:{str(row.username).casefold()}"
                if row.username
                else None
            )
        ),
    }
    alias_list = list(aliases or [])
    if row.username and row.username not in alias_list:
        alias_list = [row.username, *alias_list]
    view = {
        "id": row.id,
        "run_id": row.run_id,
        "source_telegram_id": row.source_telegram_id,
        "username": row.username,
        "title": row.title,
        "source_type": row.source_type,
        "public_url": row.public_url,
        "linked_parent_telegram_id": row.linked_parent_telegram_id,
        "is_linked_discussion": row.linked_parent_telegram_id is not None,
        "qualified_count": row.qualified_count,
        "excluded_count": row.excluded_count,
        "active_week_count": row.active_week_count,
        "ecommerce_qualified_count": row.ecommerce_qualified_count,
        "last_qualified_at": row.last_qualified_at,
        "sample_message_count": row.sample_message_count,
        "sampling_label": _sampling_label(row.sample_message_count),
        "score": row.score,
        "band": row.band,
        "truth_status": truth_status,
        "truth_label": _truth_label(truth_status),
        "verification_scanned_count": getattr(row, "verification_scanned_count", 0) or 0,
        "verification_stop_reason": getattr(row, "verification_stop_reason", None),
        "score_components": components,
        "eligibility_reasons": _eligibility_reasons(components),
        "discovery_channels": channels,
        "provenance": channels,
        "identity": identity,
        "aliases": alias_list,
        "evidence_counts": {
            "qualified": row.qualified_count,
            "excluded": row.excluded_count,
            "sample": row.sample_message_count,
            "active_weeks": row.active_week_count,
            "ecommerce_qualified": row.ecommerce_qualified_count,
        },
        "review_state": row.review_state,
        "promoted_source_id": row.promoted_source_id,
        "source_id": row.source_id,
        "existing_source": existing,
        "lifecycle_state": lifecycle,
        "noise": noise,
        "version": row.version,
        "dismiss_reason": row.dismiss_reason,
        "suppress": suppress,
    }
    view["rank_reason"] = _rank_reason(view)
    return view


def _evidence_item(row: SourceDiscoveryEvidence) -> dict[str, Any]:
    ordinals = _loads_json_obj(row.matched_query_ordinals_json, [])
    profiles = _loads_json_obj(row.service_profiles_json, [])
    rule_ids = _loads_json_obj(getattr(row, "matched_rule_ids_json", None), [])
    return {
        "excerpt": row.excerpt or "",
        "permalink": row.permalink,
        "category": row.detection_category,
        "service_profiles": profiles if isinstance(profiles, list) else [],
        "matched_query_ordinals": ordinals if isinstance(ordinals, list) else [],
        "matched_rule_ids": rule_ids if isinstance(rule_ids, list) else [],
        "is_qualified": row.is_qualified,
        "published_at": row.published_at,
    }
