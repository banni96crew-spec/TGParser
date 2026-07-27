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


class TelethonTelegramGateway:
    """Thin Telethon adapter. Connect may stub when session/secrets are absent."""

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client
        self._connected = client is not None

    async def connect(self) -> AccountSnapshot:
        presence = load_secret_presence()
        if not presence.telegram_ready:
            # Local stub mode for environments without credentials.
            self._connected = True
            return AccountSnapshot(
                schema_version=1,
                account_id=0,
                username=None,
                connected=False,
            )
        try:
            from telethon import TelegramClient  # local import — Telethon boundary

            from telegram_lead_discovery.security.secrets import require_env

            api_id = int(require_env("TG_API_ID"))
            api_hash = require_env("TG_API_HASH")
            path = session_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(str(path.with_suffix("")), api_id, api_hash)
            await self._client.connect()
            self._connected = True
            me = await self._client.get_me()
            return AccountSnapshot(
                schema_version=1,
                account_id=int(getattr(me, "id", 0) or 0),
                username=getattr(me, "username", None),
                connected=True,
            )
        except Exception as exc:  # noqa: BLE001
            mapped = _map_telethon_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise GatewayTransientError(str(exc)) from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self._client = None
        self._connected = False

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot:
        client = self._require_client()
        try:
            entity = await client.get_entity(ref.username_or_url)
            return _entity_to_snapshot(entity)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot:
        client = self._require_client()
        try:
            target = ref if isinstance(ref, int) else ref.username_or_url
            entity = await client.get_entity(target)
            return _entity_to_snapshot(entity)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]:
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
            result = await self._invoke(
                GetChannelRecommendationsRequest(channel=input_channel)
            )
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

    async def sample_public_graph_edges(
        self, request: GraphSampleRequest
    ) -> list[GraphEdgeDTO]:
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
                edge_type = (
                    "public_link" if f"t.me/{username}" in text_cf else "mention"
                )
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

    async def iter_history(
        self, request: HistoryRequest
    ) -> AsyncIterator[TelegramMessageDTO]:
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
                    peer_id = int(
                        getattr(getattr(message, "peer_id", None), "channel_id", 0)
                        or getattr(getattr(message, "peer_id", None), "chat_id", 0)
                        or 0
                    ) or None
                published = message.date
                if published is not None and published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                elif published is None:
                    published = datetime.now(UTC)
                yield TelegramMessageDTO(
                    schema_version=1,
                    source_id=request.source_id,
                    telegram_message_id=int(message.id),
                    published_at=published,
                    text=message.message or "",
                    telegram_peer_id=peer_id,
                    edited_at=None,
                    author_peer_id=None,
                    permalink=_permalink(
                        request.peer.username_normalized or "", int(message.id)
                    ),
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

    async def get_message(
        self, source: SourceRef, message_id: int
    ) -> TelegramMessageDTO | None:
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
        return TelegramMessageDTO(
            schema_version=1,
            source_id=source.source_id,
            telegram_message_id=int(message.id),
            published_at=published,
            text=message.message or "",
            telegram_peer_id=source.telegram_id,
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

    async def search_public_sources(
        self, request: DirectorySearchRequest
    ) -> list[SourceSnapshot]:
        from telethon.tl.functions.contacts import SearchRequest as ContactsSearchRequest

        result = await self._invoke(
            ContactsSearchRequest(q=request.query, limit=request.limit)
        )
        snapshots: list[SourceSnapshot] = []
        for chat in getattr(result, "chats", None) or ():
            snap = _try_public_chat_snapshot(chat)
            if snap is not None:
                snapshots.append(snap)
            if len(snapshots) >= request.limit:
                break
        return snapshots

    async def check_public_post_search_quota(
        self, query: str
    ) -> PublicPostSearchQuotaDTO:
        from telethon.tl.functions.channels import CheckSearchPostsFloodRequest

        flood = await self._invoke(CheckSearchPostsFloodRequest(query=query))
        remains = int(getattr(flood, "remains", 0) or 0)
        stars_amount = int(getattr(flood, "stars_amount", 0) or 0)
        query_is_free = bool(getattr(flood, "query_is_free", False))
        free_slot_available = query_is_free or remains > 0
        return PublicPostSearchQuotaDTO(
            schema_version=1,
            free_slot_available=free_slot_available,
            premium_required=False,
            stars_amount=stars_amount,
        )

    async def search_public_posts(
        self, request: PublicPostSearchRequest
    ) -> SearchPageDTO:
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

    async def search_source_messages(
        self, request: SourceMessageSearchRequest
    ) -> SearchPageDTO:
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

    async def get_linked_discussion(
        self, source: SourceRef
    ) -> SourceSnapshot | None:
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

    def _require_client(self) -> Any:
        if self._client is None:
            raise GatewayPermanentError("gateway_not_connected")
        return self._client

    async def _invoke(self, request: Any) -> Any:
        client = self._require_client()
        try:
            return await client(request)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def _input_peer_or_empty(self, peer_id: int) -> Any | None:
        from telethon.tl.types import InputPeerEmpty

        if peer_id <= 0:
            return InputPeerEmpty()
        client = self._require_client()
        try:
            return await client.get_input_entity(peer_id)
        except Exception:  # noqa: BLE001
            return InputPeerEmpty()


def _raise_mapped(exc: BaseException) -> BaseException:
    mapped = _map_telethon_error(exc)
    if mapped is not None:
        return mapped
    return GatewayTransientError(str(exc))


def _map_telethon_error(exc: BaseException) -> Exception | None:
    """Map Telethon/RPC errors to gateway domain exceptions."""
    try:
        from telethon import errors as te
    except ImportError:  # pragma: no cover
        return None

    if isinstance(exc, te.FloodWaitError):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=seconds))
    if isinstance(exc, getattr(te, "FloodPremiumWaitError", ())):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=seconds))

    if isinstance(
        exc,
        te.AuthKeyError
        | te.AuthKeyUnregisteredError
        | te.SessionExpiredError
        | te.SessionRevokedError
        | te.UnauthorizedError,
    ):
        return GatewayUnauthorized(str(exc))

    frozen_cls = getattr(te, "FrozenMethodInvalidError", None)
    if frozen_cls is not None and isinstance(exc, frozen_cls):
        return GatewayFrozen(str(exc))

    if isinstance(exc, te.ChannelPrivateError | te.ChatForbiddenError):
        return GatewaySourceInaccessible(str(exc))

    premium_cls = getattr(te, "PremiumAccountRequiredError", None)
    if premium_cls is not None and isinstance(exc, premium_cls):
        return GatewayPremiumRequired(str(exc))

    if isinstance(exc, te.QueryTooShortError | te.SearchQueryEmptyError):
        return GatewayInvalidSearchQuery(str(exc))

    unavailable_cls = getattr(te, "SearchWithLinkNotSupportedError", None)
    if unavailable_cls is not None and isinstance(exc, unavailable_cls):
        return GatewaySearchUnavailable(str(exc))

    if isinstance(exc, te.ServerError | te.TimedOutError):
        return GatewayTransientError(str(exc))

    if isinstance(exc, te.RPCError):
        message = (getattr(exc, "message", "") or str(exc)).upper()
        if "PREMIUM" in message:
            return GatewayPremiumRequired(str(exc))
        if "FLOOD" in message:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=max(seconds, 1)))
        if getattr(exc, "code", None) in {400, 403}:
            return GatewayPermanentError(str(exc))
        if getattr(exc, "code", None) in {500, 503}:
            return GatewayTransientError(str(exc))

    return None


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


_USERNAME_TOKEN = regex.compile(r"[a-zA-Z0-9_]{5,32}")
_MENTION_RE = regex.compile(r"(?<![a-zA-Z0-9_])@([a-zA-Z0-9_]{5,32})\b")
_TME_RE = regex.compile(
    r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32})(?:/[0-9]+)?(?:\?[^\s]*)?",
    flags=regex.IGNORECASE,
)
_PRIVATE_TME_PREFIXES = frozenset(
    {"joinchat", "addstickers", "share", "proxy", "socks", "c", "s"}
)
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


def _permalink(username: str, message_id: int) -> str | None:
    if not username:
        return None
    return f"https://t.me/{username}/{message_id}"


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

    return TelegramUpdateDTO(
        schema_version=1,
        event_type=event_type,  # type: ignore[arg-type]
        telegram_peer_id=peer_id,
        observed_at=observed,
        message=TelegramMessageDTO(
            schema_version=1,
            source_id=0,
            telegram_message_id=msg_id,
            published_at=published,
            text=getattr(message, "message", None) or "",
            telegram_peer_id=peer_id,
            edited_at=edited,
            permalink=_permalink(username or "", msg_id),
        ),
    )
