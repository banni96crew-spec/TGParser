from __future__ import annotations

from typing import Any

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    DiscoveryRunQuery,
    HistoryRequest,
    TelegramPeerRef,
)
from telegram_lead_discovery.source_discovery.worker_parts.core import _save_cursor

_MISSING = object()


def _history_request(
    *,
    telegram_id: int,
    username: str | None,
    page_limit: int,
    offset_id: int,
) -> HistoryRequest:
    return HistoryRequest(
        schema_version=1,
        source_id=0,
        peer=TelegramPeerRef(
            schema_version=1,
            telegram_peer_id=telegram_id,
            username_normalized=username,
        ),
        limit=page_limit,
        purpose="scouting_verification",
        continuation_cursor=str(offset_id) if offset_id else None,
        before_published_at=None,
        after_published_at=None,
    )


def _save_history_progress(
    query: DiscoveryRunQuery,
    *,
    offset_id: int,
    scanned: int,
    distinct_hashes: set[str],
    noise_kept: int,
    stop_reason: str | None | object = _MISSING,
) -> None:
    payload: dict[str, Any] = {
        "offset_id": offset_id,
        "scanned": scanned,
        "distinct_hashes": sorted(distinct_hashes),
        "noise_kept": noise_kept,
    }
    if stop_reason is not _MISSING:
        payload["stop_reason"] = stop_reason
    _save_cursor(query, payload)
