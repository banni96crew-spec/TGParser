"""Telethon-only TelegramGateway adapter (COL)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import regex

from telegram_lead_discovery.collector.ports import (
    AccountSnapshot,
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySearchUnavailable,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
    GlobalSearchRequest,
    GraphEdgeDTO,
    GraphSampleRequest,
    HistoryRequest,
    PublicPostSearchQuotaDTO,
    PublicPostSearchRequest,
    PublicSourceRef,
    SearchCursor,
    SearchMessageHitDTO,
    SearchPageDTO,
    SourceMessageSearchRequest,
    SourceRef,
    SourceSnapshot,
    TelegramMessageDTO,
    TelegramPeerRef,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.security.secrets import load_secret_presence
from telegram_lead_discovery.security.session_paths import session_path

_EXCERPT_MAX_CODEPOINTS = 240


from telegram_lead_discovery.collector.adapter.telethon_parts.error_mapping import _raise_mapped
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _entity_to_snapshot,
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.graph_mapping import (
    _forward_origin_edge,
    _usernames_from_message_text,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.message_mapping import (
    _messages_result_to_page,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.cursor_mapping import (
    _decode_cursor,
    _event_to_update_dto,
    _permalink,
)


class TelethonGraphMixin:
    async def get_recommendations(self, source: SourceRef, limit: int) -> list[SourceSnapshot]:
        """Public channel recommendations via GetChannelRecommendations (SRC-003).

        Returns only public channel|megagroup|group with username. Never joins.
        """
        from telethon.tl.functions.channels import GetChannelRecommendationsRequest
        from telethon.tl.types import InputChannel

        peer_id = source.telegram_id
        if peer_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        client = self._require_client()
        try:
            entity = await client.get_entity(peer_id)
            input_channel = InputChannel(
                channel_id=int(entity.id),
                access_hash=int(getattr(entity, "access_hash", 0) or 0),
            )
            result = await self._invoke(GetChannelRecommendationsRequest(channel=input_channel))
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

        snapshots: list[SourceSnapshot] = []
        for chat in getattr(result, "chats", None) or ():
            snap = _try_public_chat_snapshot(chat)
            if snap is None:
                continue
            snapshots.append(snap)
            if len(snapshots) >= limit:
                break
        return snapshots

    async def sample_public_graph_edges(self, request: GraphSampleRequest) -> list[GraphEdgeDTO]:
        """Sample recent messages for public mention / t.me link / forward origin.

        Private invite links and peers without public username are skipped.
        Never auto-joins.
        """
        peer_id = request.source.telegram_id
        if peer_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        client = self._require_client()
        limit = max(0, min(int(request.message_limit), 50))
        if limit == 0:
            return []
        try:
            messages = await client.get_messages(peer_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

        edges: list[GraphEdgeDTO] = []
        seen: set[tuple[str, str]] = set()
        for message in messages or ():
            msg_id = int(getattr(message, "id", 0) or 0)
            text = getattr(message, "message", None) or ""
            text_cf = text.casefold()
            for username in _usernames_from_message_text(text):
                key = ("ref", username)
                if key in seen:
                    continue
                seen.add(key)
                edge_type = "public_link" if f"t.me/{username}" in text_cf else "mention"
                edges.append(
                    GraphEdgeDTO(
                        schema_version=1,
                        edge_type=edge_type,  # type: ignore[arg-type]
                        seed_telegram_id=peer_id,
                        raw_reference=(
                            f"https://t.me/{username}"
                            if edge_type == "public_link"
                            else f"@{username}"
                        ),
                        normalized_username=username,
                        evidence_message_id=msg_id or None,
                    )
                )
            fwd_edge = _forward_origin_edge(message, seed_telegram_id=peer_id)
            if fwd_edge is not None:
                key = (
                    "forward_origin",
                    fwd_edge.normalized_username or fwd_edge.raw_reference,
                )
                if key not in seen:
                    seen.add(key)
                    edges.append(fwd_edge)
        return edges
