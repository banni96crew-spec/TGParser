from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from telegram_lead_discovery.collector.ports import SearchMessageHitDTO, SearchPageDTO
from telegram_lead_discovery.collector.adapter.telethon_parts.cursor_mapping import _encode_cursor
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _chat_for_peer,
    _excerpt,
    _permalink,
    _try_public_chat_snapshot,
)

_EXCERPT_MAX_CODEPOINTS = 240


def _messages_result_to_page(
    result: Any,
    *,
    limit: int,
    fallback_source_id: int | None = None,
) -> SearchPageDTO:
    chats_by_id = {
        int(chat.id): chat for chat in (getattr(result, "chats", None) or ()) if hasattr(chat, "id")
    }
    hits: list[SearchMessageHitDTO] = []
    messages = list(getattr(result, "messages", None) or ())
    last_peer_id = 0
    last_msg_id = 0

    for message in messages:
        text = getattr(message, "message", None)
        if text is None and not hasattr(message, "id"):
            continue
        msg_id = int(getattr(message, "id", 0) or 0)
        if msg_id <= 0:
            continue
        peer = getattr(message, "peer_id", None)
        chat = _chat_for_peer(peer, chats_by_id)
        snap = _try_public_chat_snapshot(chat) if chat is not None else None
        if snap is None and fallback_source_id is not None:
            chat = chats_by_id.get(fallback_source_id)
            snap = _try_public_chat_snapshot(chat) if chat is not None else None
        if snap is None:
            continue
        published = getattr(message, "date", None) or datetime.now(UTC)
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        body = text if isinstance(text, str) else ""
        hits.append(
            SearchMessageHitDTO(
                schema_version=1,
                source=snap,
                telegram_message_id=msg_id,
                published_at=published,
                permalink=_permalink(snap.username, msg_id),
                excerpt=_excerpt(body, _EXCERPT_MAX_CODEPOINTS),
            )
        )
        last_msg_id = msg_id
        last_peer_id = snap.telegram_id

    next_rate = getattr(result, "next_rate", None)
    truncated = next_rate is not None or len(messages) >= limit
    next_cursor = None
    if truncated and last_msg_id > 0:
        next_cursor = _encode_cursor(
            offset_rate=int(next_rate or 0),
            offset_id=last_msg_id,
            offset_peer_id=last_peer_id,
        )
    return SearchPageDTO(
        schema_version=1,
        hits=tuple(hits),
        next_cursor=next_cursor,
        truncated=truncated and next_cursor is not None,
    )
