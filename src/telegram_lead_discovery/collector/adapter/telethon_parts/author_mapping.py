"""In-memory Telethon sender classification without extra network requests."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.collector.port_parts.messages import AuthorKind


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def classify_message_author(message: Any) -> tuple[AuthorKind, int | None]:
    """Return closed author kind and ephemeral raw peer id (COL-027)."""
    via_bot_id = _positive_int(getattr(message, "via_bot_id", None))
    if via_bot_id is not None:
        return "bot", via_bot_id

    peer = getattr(message, "from_id", None)
    sender = getattr(message, "sender", None)
    peer_name = type(peer).__name__
    sender_name = type(sender).__name__

    user_id = _positive_int(getattr(peer, "user_id", None))
    if user_id is not None or peer_name == "PeerUser":
        if sender is None:
            return "unknown", user_id
        if bool(getattr(sender, "bot", False)):
            return "bot", user_id
        if sender_name == "User" or hasattr(sender, "bot"):
            return "user", user_id
        return "unknown", user_id

    channel_id = _positive_int(getattr(peer, "channel_id", None))
    if channel_id is not None or peer_name == "PeerChannel" or sender_name == "Channel":
        return "channel", channel_id or _positive_int(getattr(sender, "id", None))

    if getattr(message, "post_author", None):
        return "anonymous", None
    return "unknown", None


__all__ = ["classify_message_author"]
