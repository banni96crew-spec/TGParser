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


class TelethonSearchMixin:
    async def search_global(self, request: GlobalSearchRequest) -> SearchPageDTO:
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

        offset_rate, offset_id, offset_peer_id = _decode_cursor(request.cursor)
        offset_peer = await self._input_peer_or_empty(offset_peer_id)
        tl_request = SearchGlobalRequest(
            q=request.query,
            filter=InputMessagesFilterEmpty(),
            min_date=None,
            max_date=None,
            offset_rate=offset_rate,
            offset_peer=offset_peer if offset_peer is not None else InputPeerEmpty(),
            offset_id=offset_id,
            limit=request.limit,
            broadcasts_only=True if request.broadcasts_only else None,
            groups_only=True if request.groups_only else None,
            users_only=None,
            folder_id=None,
        )
        result = await self._invoke(tl_request)
        return _messages_result_to_page(result, limit=request.limit)

    async def search_public_sources(self, request: DirectorySearchRequest) -> list[SourceSnapshot]:
        from telethon.tl.functions.contacts import SearchRequest as ContactsSearchRequest

        result = await self._invoke(ContactsSearchRequest(q=request.query, limit=request.limit))
        snapshots: list[SourceSnapshot] = []
        for chat in getattr(result, "chats", None) or ():
            snap = _try_public_chat_snapshot(chat)
            if snap is not None:
                snapshots.append(snap)
            if len(snapshots) >= request.limit:
                break
        return snapshots

    async def check_public_post_search_quota(self, query: str) -> PublicPostSearchQuotaDTO:
        from telethon.tl.functions.channels import CheckSearchPostsFloodRequest

        try:
            flood = await self._invoke(CheckSearchPostsFloodRequest(query=query))
        except GatewayPremiumRequired:
            return PublicPostSearchQuotaDTO(
                schema_version=1,
                free_slot_available=False,
                premium_required=True,
                stars_amount=0,
            )
        remains = int(getattr(flood, "remains", 0) or 0)
        stars_amount = int(getattr(flood, "stars_amount", 0) or 0)
        query_is_free = bool(getattr(flood, "query_is_free", False))
        free_slot_available = query_is_free or remains > 0
        # Truthful Premium vs Stars (D-068): PremiumAccountRequired is mapped above;
        # Stars paid slot is remains==0 with stars_amount>0 (quota_exhausted path).
        premium_required = False
        return PublicPostSearchQuotaDTO(
            schema_version=1,
            free_slot_available=free_slot_available,
            premium_required=premium_required,
            stars_amount=stars_amount,
        )

    async def search_public_posts(self, request: PublicPostSearchRequest) -> SearchPageDTO:
        from telethon.tl.functions.channels import SearchPostsRequest
        from telethon.tl.types import InputPeerEmpty

        # Defense in depth (D-050/D-051): never pay Stars; refuse paid slot.
        quota = await self.check_public_post_search_quota(request.query)
        if quota.premium_required:
            raise GatewayPremiumRequired("premium_required")
        if not quota.free_slot_available and quota.stars_amount > 0:
            raise GatewaySearchQuotaExhausted("quota_exhausted")
        if not quota.free_slot_available:
            raise GatewaySearchQuotaExhausted("quota_exhausted")

        offset_rate, offset_id, offset_peer_id = _decode_cursor(request.cursor)
        offset_peer = await self._input_peer_or_empty(offset_peer_id)
        # Zero Stars (D-050): allow_paid_stars is None — never accept Stars from UI/settings.
        tl_request = SearchPostsRequest(
            offset_rate=offset_rate,
            offset_peer=offset_peer if offset_peer is not None else InputPeerEmpty(),
            offset_id=offset_id,
            limit=request.limit,
            hashtag=None,
            query=request.query,
            allow_paid_stars=None,
        )
        result = await self._invoke(tl_request)
        return _messages_result_to_page(result, limit=request.limit)

    async def search_source_messages(self, request: SourceMessageSearchRequest) -> SearchPageDTO:
        from telethon.tl.functions.messages import SearchRequest as MessagesSearchRequest
        from telethon.tl.types import InputMessagesFilterEmpty

        peer_id = request.source.telegram_id
        if peer_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        input_peer = await self._input_peer_or_empty(peer_id)
        if input_peer is None:
            raise GatewaySourceInaccessible(f"unresolvable:{peer_id}")

        _offset_rate, offset_id, _peer = _decode_cursor(request.cursor)
        tl_request = MessagesSearchRequest(
            peer=input_peer,
            q=request.query,
            filter=InputMessagesFilterEmpty(),
            min_date=request.published_after,
            max_date=request.published_before,
            offset_id=offset_id,
            add_offset=0,
            limit=request.limit,
            max_id=0,
            min_id=0,
            hash=0,
        )
        result = await self._invoke(tl_request)
        return _messages_result_to_page(
            result,
            limit=request.limit,
            fallback_source_id=peer_id,
        )

    async def get_linked_discussion(self, source: SourceRef) -> SourceSnapshot | None:
        from telethon.tl.functions.channels import GetFullChannelRequest
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
            result = await self._invoke(GetFullChannelRequest(channel=input_channel))
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

        linked_id = getattr(getattr(result, "full_chat", None), "linked_chat_id", None)
        if not linked_id:
            return None
        for chat in getattr(result, "chats", None) or ():
            if int(getattr(chat, "id", 0) or 0) == int(linked_id):
                return _try_public_chat_snapshot(chat)
        return None
