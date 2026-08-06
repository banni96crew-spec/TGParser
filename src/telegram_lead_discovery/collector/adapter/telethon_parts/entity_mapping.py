from __future__ import annotations

from typing import Any

from telegram_lead_discovery.collector.ports import SourceSnapshot


def _chat_for_peer(peer: Any, chats_by_id: dict[int, Any]) -> Any | None:
    if peer is None:
        return None
    channel_id = getattr(peer, "channel_id", None)
    if channel_id is not None:
        return chats_by_id.get(int(channel_id))
    chat_id = getattr(peer, "chat_id", None)
    if chat_id is not None:
        return chats_by_id.get(int(chat_id))
    return None


def _try_public_chat_snapshot(entity: Any | None) -> SourceSnapshot | None:
    if entity is None:
        return None
    username = getattr(entity, "username", None)
    if not username:
        return None
    # Public channels / megagroups / basic groups only (D-048).
    if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
        return _entity_to_snapshot(entity)
    # telethon Chat (basic group) has title but no broadcast/megagroup flags.
    if hasattr(entity, "title") and not hasattr(entity, "bot"):
        # Exclude User objects (have first_name, no title typically handled above).
        if getattr(entity, "first_name", None) is not None and not hasattr(entity, "title"):
            return None
        return _entity_to_snapshot(entity)
    return None


def _entity_to_snapshot(entity: object) -> SourceSnapshot:
    username = getattr(entity, "username", None) or ""
    title = getattr(entity, "title", None) or username
    telegram_id = int(entity.id)
    source_type = "channel"
    if getattr(entity, "megagroup", False):
        source_type = "megagroup"
    elif getattr(entity, "broadcast", False):
        source_type = "channel"
    else:
        source_type = "group"
    return SourceSnapshot(
        schema_version=1,
        telegram_id=telegram_id,
        username=username.lower(),
        title=title,
        source_type=source_type,  # type: ignore[arg-type]
        public_url=f"https://t.me/{username}" if username else None,
        accessible=True,
    )


def _excerpt(text: str, max_codepoints: int) -> str:
    if not text:
        return ""
    if len(text) <= max_codepoints:
        return text
    return text[:max_codepoints]


def _permalink(username: str, message_id: int) -> str | None:
    if not username:
        return None
    return f"https://t.me/{username}/{message_id}"
