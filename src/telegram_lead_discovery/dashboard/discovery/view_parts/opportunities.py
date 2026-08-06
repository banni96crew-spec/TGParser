"""Opportunity and evidence view-model construction."""

from __future__ import annotations

import json
from typing import Any

from telegram_lead_discovery.storage.models import (
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)

_DEFAULT_BANDS = frozenset({"review", "promising"})
_BAND_FILTER_DEFAULT = "all"
_TRUTH_LABELS = {
    "quality": "Качественные",
    "near": "Почти (1–6)",
    "inconclusive": "Недоказанные",
    "rejected": "Отклонённые",
}


def _loads_json_obj(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


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
            else (f"username:{str(row.username).casefold()}" if row.username else None)
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
