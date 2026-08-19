"""Raw, one-call Telethon operations used by graph discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from telegram_lead_discovery.collector.adapter.telethon_parts.author_mapping import (
    classify_message_author,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _permalink,
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.error_mapping import _raise_mapped
from telegram_lead_discovery.collector.adapter.telethon_parts.graph_mapping import (
    _usernames_from_message_text,
)
from telegram_lead_discovery.collector.ports import (
    GatewaySourceInaccessible,
    GraphEdgeDTO,
    GraphSampleRequest,
    GraphSampleResultDTO,
    SourceRef,
    SourceSnapshot,
    TelegramMessageDTO,
)


def _offline_input_channel(client: Any, source: SourceRef) -> Any | None:
    """Read Telethon's local entity cache without a Telegram request."""
    from telethon.tl.types import InputChannel, InputPeerChannel

    if source.telegram_id is not None and source.access_hash is not None:
        return InputChannel(
            channel_id=int(source.telegram_id),
            access_hash=int(source.access_hash),
        )
    session = getattr(client, "session", None)
    getter = getattr(session, "get_input_entity", None)
    if getter is None:
        return None
    for key in (source.telegram_id, source.username):
        if key is None:
            continue
        try:
            peer = getter(key)
        except (KeyError, ValueError, TypeError):
            continue
        if isinstance(peer, InputPeerChannel):
            return InputChannel(
                channel_id=int(peer.channel_id),
                access_hash=int(peer.access_hash),
            )
    return None


def _source_from_input_channel(source: SourceRef, channel: Any) -> SourceSnapshot:
    username = (source.username or "").lower()
    return SourceSnapshot(
        schema_version=1,
        telegram_id=int(channel.channel_id),
        username=username,
        title=username,
        source_type="channel",
        public_url=f"https://t.me/{username}" if username else None,
        accessible=True,
        access_hash=int(channel.access_hash),
    )


class TelethonGraphMixin:
    async def resolve_graph_source(self, ref: SourceRef) -> SourceSnapshot:
        """Resolve from local session, otherwise with one raw username request."""
        client = self._require_client()
        cached = _offline_input_channel(client, ref)
        if cached is not None:
            return _source_from_input_channel(ref, cached)
        if not ref.username:
            raise GatewaySourceInaccessible("seed_resolution_data_missing")

        from telethon.tl.functions.contacts import ResolveUsernameRequest

        try:
            result = await self._invoke(
                ResolveUsernameRequest(username=ref.username.lstrip("@"), referer=None)
            )
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc
        for chat in getattr(result, "chats", None) or ():
            snap = _try_public_chat_snapshot(chat)
            if snap is not None:
                return snap
        raise GatewaySourceInaccessible(f"unresolvable:{ref.username}")

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]:
        from telethon.tl.functions.channels import GetChannelRecommendationsRequest

        channel = _offline_input_channel(self._require_client(), source)
        if channel is None:
            raise GatewaySourceInaccessible("seed_resolution_data_missing")
        try:
            result = await self._invoke(
                GetChannelRecommendationsRequest(channel=channel)
            )
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc
        snapshots: list[SourceSnapshot] = []
        for chat in getattr(result, "chats", None) or ():
            snap = _try_public_chat_snapshot(chat)
            if snap is not None:
                snapshots.append(snap)
            if len(snapshots) >= max(0, int(limit)):
                break
        return snapshots

    async def sample_public_graph_edges(
        self, request: GraphSampleRequest
    ) -> list[GraphEdgeDTO]:
        return list((await self.sample_public_graph(request)).edges)

    async def sample_public_graph(
        self, request: GraphSampleRequest
    ) -> GraphSampleResultDTO:
        from telethon.tl.functions.messages import GetHistoryRequest

        source = request.source
        channel = _offline_input_channel(self._require_client(), source)
        if channel is None:
            raise GatewaySourceInaccessible("seed_resolution_data_missing")
        limit = max(0, min(int(request.message_limit), 100))
        if limit == 0:
            return GraphSampleResultDTO(schema_version=1, edges=(), messages=())
        try:
            result = await self._invoke(
                GetHistoryRequest(
                    peer=channel,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc
        peer_id = int(channel.channel_id)
        return GraphSampleResultDTO(
            schema_version=1,
            edges=tuple(_graph_edges_from_history(result, seed_telegram_id=peer_id)),
            messages=tuple(_graph_messages_from_history(result, request.source, peer_id)),
        )


def _graph_edges_from_history(result: Any, *, seed_telegram_id: int) -> list[GraphEdgeDTO]:
    chats = {
        int(getattr(chat, "id", 0) or 0): chat
        for chat in (getattr(result, "chats", None) or ())
    }
    edges: list[GraphEdgeDTO] = []
    seen: set[tuple[str, str]] = set()
    for message in getattr(result, "messages", None) or ():
        message_id = int(getattr(message, "id", 0) or 0) or None
        text = getattr(message, "message", None) or ""
        folded = text.casefold()
        for username in _usernames_from_message_text(text):
            key = ("reference", username)
            if key in seen:
                continue
            seen.add(key)
            method = "public_link" if f"t.me/{username}" in folded else "mention"
            edges.append(
                GraphEdgeDTO(
                    schema_version=1,
                    edge_type=method,  # type: ignore[arg-type]
                    seed_telegram_id=seed_telegram_id,
                    raw_reference=(
                        f"https://t.me/{username}" if method == "public_link" else f"@{username}"
                    ),
                    normalized_username=username,
                    evidence_message_id=message_id,
                )
            )
        fwd = getattr(message, "fwd_from", None)
        from_id = getattr(fwd, "from_id", None) if fwd is not None else None
        channel_id = getattr(from_id, "channel_id", None)
        chat = chats.get(int(channel_id)) if channel_id is not None else None
        snap = _try_public_chat_snapshot(chat)
        if snap is not None:
            key = ("forward_origin", f"peer:{snap.telegram_id}")
            if key not in seen:
                seen.add(key)
                edges.append(
                    GraphEdgeDTO(
                        schema_version=1,
                        edge_type="forward_origin",
                        seed_telegram_id=seed_telegram_id,
                        raw_reference=f"@{snap.username}",
                        normalized_username=snap.username,
                        target=snap,
                        evidence_message_id=message_id,
                    )
                )
    return edges


def _graph_messages_from_history(
    result: Any,
    source: SourceRef,
    peer_id: int,
) -> list[TelegramMessageDTO]:
    users = {
        int(getattr(user, "id", 0) or 0): user
        for user in (getattr(result, "users", None) or ())
    }
    messages: list[TelegramMessageDTO] = []
    username = source.username or ""
    for message in getattr(result, "messages", None) or ():
        message_id = int(getattr(message, "id", 0) or 0)
        if message_id <= 0:
            continue
        published = getattr(message, "date", None) or datetime.now(UTC)
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        author_kind, author_peer_id = classify_message_author(message)
        if author_kind == "unknown" and author_peer_id in users:
            author_kind = "bot" if bool(getattr(users[author_peer_id], "bot", False)) else "user"
        messages.append(
            TelegramMessageDTO(
                schema_version=2,
                source_id=source.source_id,
                telegram_message_id=message_id,
                published_at=published,
                text=getattr(message, "message", None) or "",
                telegram_peer_id=peer_id,
                author_peer_id=author_peer_id,
                author_kind=author_kind,
                permalink=_permalink(username, message_id),
            )
        )
    return messages


__all__ = ["TelethonGraphMixin", "_offline_input_channel"]
