from __future__ import annotations

from typing import Any

import regex

from telegram_lead_discovery.collector.ports import GraphEdgeDTO
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _try_public_chat_snapshot,
)


_USERNAME_TOKEN = regex.compile(r"[a-zA-Z0-9_]{5,32}")
_MENTION_RE = regex.compile(r"(?<![a-zA-Z0-9_])@([a-zA-Z0-9_]{5,32})\b")
_TME_RE = regex.compile(
    r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32})(?:/[0-9]+)?(?:\?[^\s]*)?",
    flags=regex.IGNORECASE,
)
_PRIVATE_TME_PREFIXES = frozenset({"joinchat", "addstickers", "share", "proxy", "socks", "c", "s"})
_REGEX_TIMEOUT = 0.05


def _usernames_from_message_text(text: str) -> list[str]:
    """Extract public @username / t.me/<user> tokens; skip invite-only paths."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    try:
        for match in _TME_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token in _PRIVATE_TME_PREFIXES or token.startswith("+"):
                continue
            if token not in seen:
                seen.add(token)
                found.append(token)
        for match in _MENTION_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token not in seen:
                seen.add(token)
                found.append(token)
    except TimeoutError:
        return found
    return found


def _forward_origin_edge(message: Any, *, seed_telegram_id: int) -> GraphEdgeDTO | None:
    """Return public forward_origin edge only when origin username is verifiable."""
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None
    # Prefer channel username when Telethon exposes it on the forwarded header.
    username = getattr(fwd, "from_name", None)
    # Telethon may attach resolved chat on message; prefer explicit username attr.
    from_id = getattr(fwd, "from_id", None)
    channel_id = getattr(from_id, "channel_id", None) if from_id is not None else None
    # Without a resolvable public username, skip (SRC-042 unconfirmed).
    saved = getattr(message, "forward", None)
    chat = getattr(saved, "chat", None) if saved is not None else None
    chat_username = getattr(chat, "username", None) if chat is not None else None
    public_username = (chat_username or "").lower() or None
    if public_username and _USERNAME_TOKEN.fullmatch(public_username, timeout=_REGEX_TIMEOUT):
        snap = _try_public_chat_snapshot(chat)
        return GraphEdgeDTO(
            schema_version=1,
            edge_type="forward_origin",
            seed_telegram_id=seed_telegram_id,
            raw_reference=f"@{public_username}",
            normalized_username=public_username,
            target=snap,
            evidence_message_id=int(getattr(message, "id", 0) or 0) or None,
        )
    # Display name alone is not a public identity — skip.
    _ = username
    _ = channel_id
    return None
