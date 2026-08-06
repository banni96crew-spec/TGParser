from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from telegram_lead_discovery.collector.ports import (
    SearchCursor,
    TelegramMessageDTO,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import _permalink
from telegram_lead_discovery.collector.adapter.telethon_parts.author_mapping import (
    classify_message_author,
)


def _encode_cursor(*, offset_rate: int, offset_id: int, offset_peer_id: int) -> SearchCursor:
    token = json.dumps(
        {
            "offset_rate": offset_rate,
            "offset_id": offset_id,
            "offset_peer_id": offset_peer_id,
        },
        separators=(",", ":"),
    )
    return SearchCursor(schema_version=1, token=token)


def _decode_cursor(cursor: SearchCursor | None) -> tuple[int, int, int]:
    if cursor is None or not cursor.token:
        return 0, 0, 0
    token = cursor.token
    try:
        payload = json.loads(token)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        try:
            return (
                int(payload.get("offset_rate", 0) or 0),
                int(payload.get("offset_id", 0) or 0),
                int(payload.get("offset_peer_id", 0) or 0),
            )
        except (TypeError, ValueError):
            return 0, 0, 0
    # Backward-compatible numeric offset tokens (fake gateway style).
    try:
        return 0, int(token), 0
    except ValueError:
        return 0, 0, 0


def _peer_id_from_telethon_peer(peer: Any) -> int | None:
    if peer is None:
        return None
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if value is not None:
            return int(value)
    return None


def _event_to_update_dto(event: Any) -> TelegramUpdateDTO | None:
    """Normalize Telethon NewMessage / MessageEdited / MessageDeleted to DTO."""
    observed = datetime.now(UTC)
    message = getattr(event, "message", None)
    deleted_ids = getattr(event, "deleted_ids", None)

    if deleted_ids:
        peer_id = _peer_id_from_telethon_peer(getattr(event, "peer", None))
        # Emit one update per deleted id (stable identity).
        mid = int(deleted_ids[0])
        return TelegramUpdateDTO(
            schema_version=1,
            event_type="message_deleted",
            telegram_peer_id=peer_id,
            observed_at=observed,
            message=TelegramMessageDTO(
                schema_version=1,
                source_id=0,
                telegram_message_id=mid,
                published_at=observed,
                text="",
                telegram_peer_id=peer_id,
                is_deleted=True,
            ),
        )

    if message is None:
        return None

    msg_id = int(getattr(message, "id", 0) or 0)
    if msg_id <= 0:
        return None
    peer_id = _peer_id_from_telethon_peer(getattr(message, "peer_id", None))
    published = getattr(message, "date", None) or observed
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    edited = getattr(message, "edit_date", None)
    if edited is not None and edited.tzinfo is None:
        edited = edited.replace(tzinfo=UTC)
    event_type = "message_edited" if edited is not None else "message_new"
    # MessageEdited events always map to edited even without edit_date.
    if type(event).__name__ in {"MessageEdited", "MessageEditedEvent"} or (
        getattr(event, "original_update", None) is not None
        and "Edit" in type(getattr(event, "original_update", object())).__name__
    ):
        event_type = "message_edited"

    username = None
    chat = getattr(event, "chat", None)
    if chat is not None:
        username = getattr(chat, "username", None)
    author_kind, author_peer_id = classify_message_author(message)

    return TelegramUpdateDTO(
        schema_version=1,
        event_type=event_type,  # type: ignore[arg-type]
        telegram_peer_id=peer_id,
        observed_at=observed,
        message=TelegramMessageDTO(
            schema_version=2,
            source_id=0,
            telegram_message_id=msg_id,
            published_at=published,
            text=getattr(message, "message", None) or "",
            telegram_peer_id=peer_id,
            edited_at=edited,
            author_peer_id=author_peer_id,
            author_kind=author_kind,
            permalink=_permalink(username or "", msg_id),
        ),
    )
