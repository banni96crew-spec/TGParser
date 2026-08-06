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
from telegram_lead_discovery.collector.adapter.telethon_parts.author_mapping import (
    classify_message_author,
)


class TelethonMessageMixin:
    async def iter_history(self, request: HistoryRequest) -> AsyncIterator[TelegramMessageDTO]:
        client = self._require_client()
        # COL-023 / D-064: resolve via TelegramPeerRef only — never DB source_id.
        entity = await self._resolve_peer_entity(request.peer)
        offset_id = 0
        if request.continuation_cursor:
            try:
                offset_id = int(request.continuation_cursor)
            except ValueError:
                offset_id = 0
        min_id = request.after_message_id or 0
        try:
            async for message in client.iter_messages(
                entity,
                limit=request.limit,
                min_id=min_id,
                offset_id=offset_id,
            ):
                peer_id = request.peer.telegram_peer_id
                if peer_id is None:
                    peer_id = (
                        int(
                            getattr(getattr(message, "peer_id", None), "channel_id", 0)
                            or getattr(getattr(message, "peer_id", None), "chat_id", 0)
                            or 0
                        )
                        or None
                    )
                published = message.date
                if published is not None and published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                elif published is None:
                    published = datetime.now(UTC)
                author_kind, author_peer_id = classify_message_author(message)
                yield TelegramMessageDTO(
                    schema_version=2,
                    source_id=request.source_id,
                    telegram_message_id=int(message.id),
                    published_at=published,
                    text=message.message or "",
                    telegram_peer_id=peer_id,
                    edited_at=None,
                    author_peer_id=author_peer_id,
                    author_kind=author_kind,
                    permalink=_permalink(request.peer.username_normalized or "", int(message.id)),
                )
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]:
        client = self._require_client()
        queue: asyncio.Queue[TelegramUpdateDTO | None] = asyncio.Queue()

        async def _handler(event: Any) -> None:
            update = _event_to_update_dto(event)
            if update is not None:
                await queue.put(update)

        try:
            from telethon import events

            client.add_event_handler(_handler, events.NewMessage)
            client.add_event_handler(_handler, events.MessageEdited)
            client.add_event_handler(_handler, events.MessageDeleted)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            try:
                client.remove_event_handler(_handler)
            except Exception:  # noqa: BLE001
                pass

    async def get_message(self, source: SourceRef, message_id: int) -> TelegramMessageDTO | None:
        client = self._require_client()
        # Prefer telegram_id / username — never fall back to DB source_id (D-064).
        if source.telegram_id is not None:
            entity: Any = source.telegram_id
        elif source.username:
            entity = source.username
        else:
            raise GatewaySourceInaccessible("missing_peer_ref")
        try:
            message = await client.get_messages(entity, ids=message_id)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc
        if message is None:
            return None
        published = message.date
        if published is not None and published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        elif published is None:
            published = datetime.now(UTC)
        author_kind, author_peer_id = classify_message_author(message)
        return TelegramMessageDTO(
            schema_version=2,
            source_id=source.source_id,
            telegram_message_id=int(message.id),
            published_at=published,
            text=message.message or "",
            telegram_peer_id=source.telegram_id,
            author_peer_id=author_peer_id,
            author_kind=author_kind,
        )

    async def _resolve_peer_entity(self, peer: TelegramPeerRef) -> Any:
        """Map TelegramPeerRef to a Telethon entity key (never DB source_id)."""
        client = self._require_client()
        if peer.telegram_peer_id is not None and peer.access_hash is not None:
            from telethon.tl.types import InputPeerChannel

            pid = int(peer.telegram_peer_id)
            access = int(peer.access_hash)
            # Channels use negative/marked ids in some APIs; prefer InputPeerChannel
            # when access_hash is present (public channels/megagroups).
            if pid < 0:
                return InputPeerChannel(channel_id=abs(pid), access_hash=access)
            try:
                return await client.get_input_entity(pid)
            except Exception:  # noqa: BLE001
                return InputPeerChannel(channel_id=pid, access_hash=access)
        if peer.username_normalized:
            try:
                return await client.get_entity(peer.username_normalized)
            except Exception as exc:  # noqa: BLE001
                raise _raise_mapped(exc) from exc
        if peer.telegram_peer_id is not None:
            try:
                return await client.get_entity(peer.telegram_peer_id)
            except Exception as exc:  # noqa: BLE001
                raise _raise_mapped(exc) from exc
        raise GatewayPermanentError("invalid_peer_ref")
