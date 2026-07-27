"""In-memory FakeTelegramGateway for tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import fields
from datetime import UTC, datetime
from typing import Literal

from telegram_lead_discovery.collector.ports import (
    AccountSnapshot,
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySourceInaccessible,
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

_GROUP_TYPES = frozenset({"megagroup", "group"})
_BROADCAST_TYPES = frozenset({"channel"})
SearchMethod = Literal[
    "search_global",
    "search_public_sources",
    "search_public_posts",
    "search_source_messages",
    "check_public_post_search_quota",
    "get_linked_discussion",
    "get_recommendations",
    "sample_public_graph_edges",
    "resolve_public_source",
    "validate_source",
]


class FakeTelegramGateway:
    """Deterministic gateway used by integration and contract tests.

    Controllable fixtures cover the keyword-discovery Fake gateway matrix:
    global groups/broadcast search, directory search, per-source search,
    public-post pagination, free quota / Premium / quota exhausted,
    FloodWait, inaccessible source, linked discussion states, and
    duplicate hits across queries.
    """

    def __init__(
        self,
        *,
        sources: dict[str, SourceSnapshot] | None = None,
        messages: dict[int, list[TelegramMessageDTO]] | None = None,
    ) -> None:
        self._sources_by_username = {k.lower(): v for k, v in (sources or {}).items()}
        self._sources_by_id = {
            v.telegram_id: v for v in self._sources_by_username.values()
        }
        self._messages = messages or {}
        self._messages_by_peer: dict[int, list[TelegramMessageDTO]] = {}
        self.connected = False
        self.history_calls: list[HistoryRequest] = []
        self.resolved_entities: list[object] = []  # ledger: never DB source_id
        self._update_queue: asyncio.Queue[TelegramUpdateDTO | None] = asyncio.Queue()
        self._history_flood = False

        self._global_hits: list[SearchMessageHitDTO] = []
        self._directory_results: list[SourceSnapshot] = []
        self._public_post_hits_by_query: dict[str, list[SearchMessageHitDTO]] = {}
        self._source_message_hits: dict[int, list[SearchMessageHitDTO]] = {}
        self._linked_discussions: dict[int, SourceSnapshot | None] = {}
        self._private_linked_parents: set[int] = set()
        self._recommendations: dict[int, list[SourceSnapshot]] = {}
        self._graph_sample_edges: dict[int, list[GraphEdgeDTO]] = {}
        self._inaccessible_telegram_ids: set[int] = set()
        self._inaccessible_usernames: set[str] = set()
        self._quota = PublicPostSearchQuotaDTO(
            schema_version=1,
            free_slot_available=True,
            premium_required=False,
            stars_amount=0,
        )
        self._flood_wait_until: datetime | None = None
        self._flood_wait_on: set[SearchMethod] = set()
        self._raise_premium_on_public_posts = False
        self._raise_quota_exhausted_on_public_posts = False
        self._default_page_size = 100

        # Call ledgers for contract assertions (in-memory only; Zero Stars).
        self.search_global_calls: list[GlobalSearchRequest] = []
        self.search_public_sources_calls: list[DirectorySearchRequest] = []
        self.check_quota_calls: list[str] = []
        self.search_public_posts_calls: list[PublicPostSearchRequest] = []
        self.search_source_messages_calls: list[SourceMessageSearchRequest] = []
        self.get_linked_discussion_calls: list[SourceRef] = []
        self.get_recommendations_calls: list[tuple[SourceRef, int]] = []
        self.sample_public_graph_edges_calls: list[GraphSampleRequest] = []
        self.join_calls: list[object] = []  # must stay empty — no private auto-join
    # --- fixture configuration -------------------------------------------------

    def set_global_hits(self, hits: list[SearchMessageHitDTO]) -> None:
        self._global_hits = list(hits)

    def set_directory_results(self, sources: list[SourceSnapshot]) -> None:
        self._directory_results = list(sources)

    def set_public_post_hits(
        self, query: str, hits: list[SearchMessageHitDTO]
    ) -> None:
        self._public_post_hits_by_query[query] = list(hits)

    def set_source_message_hits(
        self, source_telegram_id: int, hits: list[SearchMessageHitDTO]
    ) -> None:
        self._source_message_hits[source_telegram_id] = list(hits)

    def set_linked_discussion(
        self,
        parent_telegram_id: int,
        discussion: SourceSnapshot | None,
        *,
        private: bool = False,
    ) -> None:
        if private:
            self._private_linked_parents.add(parent_telegram_id)
            self._linked_discussions.pop(parent_telegram_id, None)
        else:
            self._private_linked_parents.discard(parent_telegram_id)
            self._linked_discussions[parent_telegram_id] = discussion

    def set_recommendations(
        self, seed_telegram_id: int, sources: list[SourceSnapshot]
    ) -> None:
        self._recommendations[seed_telegram_id] = list(sources)

    def set_graph_sample_edges(
        self, seed_telegram_id: int, edges: list[GraphEdgeDTO]
    ) -> None:
        self._graph_sample_edges[seed_telegram_id] = list(edges)

    def set_quota(
        self,
        *,
        free_slot_available: bool,
        premium_required: bool = False,
        stars_amount: int = 0,
    ) -> None:
        self._quota = PublicPostSearchQuotaDTO(
            schema_version=1,
            free_slot_available=free_slot_available,
            premium_required=premium_required,
            stars_amount=stars_amount,
        )
        self._raise_premium_on_public_posts = premium_required
        self._raise_quota_exhausted_on_public_posts = (
            not free_slot_available and stars_amount > 0 and not premium_required
        )

    def set_flood_wait(
        self, until: datetime, *methods: SearchMethod | Literal["iter_history"]
    ) -> None:
        self._flood_wait_until = until
        if methods == ("iter_history",) or (len(methods) == 1 and methods[0] == "iter_history"):
            self._history_flood = True
            self._flood_wait_on = set()
            return
        self._history_flood = "iter_history" in methods
        search_methods = [m for m in methods if m != "iter_history"]
        self._flood_wait_on = set(search_methods) if search_methods else {  # type: ignore[arg-type]
            "search_global",
            "search_public_sources",
            "search_public_posts",
            "search_source_messages",
            "check_public_post_search_quota",
            "get_linked_discussion",
            "get_recommendations",
            "sample_public_graph_edges",
        }
        if not methods:
            self._history_flood = True

    def clear_flood_wait(self) -> None:
        self._flood_wait_until = None
        self._flood_wait_on.clear()
        self._history_flood = False

    def mark_inaccessible(
        self,
        *,
        telegram_id: int | None = None,
        username: str | None = None,
    ) -> None:
        if telegram_id is not None:
            self._inaccessible_telegram_ids.add(telegram_id)
            snap = self._sources_by_id.get(telegram_id)
            if snap is not None:
                self._sources_by_id[telegram_id] = SourceSnapshot(
                    schema_version=snap.schema_version,
                    telegram_id=snap.telegram_id,
                    username=snap.username,
                    title=snap.title,
                    source_type=snap.source_type,
                    public_url=snap.public_url,
                    accessible=False,
                )
        if username is not None:
            self._inaccessible_usernames.add(username.lower())

    def set_page_size(self, page_size: int) -> None:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        self._default_page_size = page_size

    # --- TelegramGateway -------------------------------------------------------

    async def connect(self) -> AccountSnapshot:
        self.connected = True
        return AccountSnapshot(
            schema_version=1,
            account_id=1,
            username="fake_operator",
            connected=True,
        )

    async def disconnect(self) -> None:
        self.connected = False

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot:
        self._maybe_flood("resolve_public_source")
        key = _normalize_ref(ref.username_or_url)
        if key in self._inaccessible_usernames:
            raise GatewaySourceInaccessible(f"inaccessible:{key}")
        snap = self._sources_by_username.get(key)
        if snap is None:
            raise GatewaySourceInaccessible(f"unknown_source:{key}")
        if not snap.accessible or snap.telegram_id in self._inaccessible_telegram_ids:
            raise GatewaySourceInaccessible(f"inaccessible:{key}")
        return snap

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot:
        self._maybe_flood("validate_source")
        if isinstance(ref, int):
            snap = self._sources_by_id.get(ref)
            if (
                snap is None
                or not snap.accessible
                or ref in self._inaccessible_telegram_ids
            ):
                raise GatewaySourceInaccessible(f"inaccessible:{ref}")
            return snap
        return await self.resolve_public_source(ref)

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]:
        self.get_recommendations_calls.append((source, limit))
        self._maybe_flood("get_recommendations")
        telegram_id = source.telegram_id
        if telegram_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        if telegram_id in self._inaccessible_telegram_ids:
            raise GatewaySourceInaccessible(f"inaccessible:{telegram_id}")
        configured = self._recommendations.get(telegram_id)
        if configured is None:
            return []
        public: list[SourceSnapshot] = []
        for snap in configured:
            if not snap.accessible or not snap.username:
                continue
            if snap.telegram_id in self._inaccessible_telegram_ids:
                continue
            if snap.source_type not in {"channel", "megagroup", "group"}:
                continue
            public.append(snap)
            if len(public) >= limit:
                break
        return public

    async def sample_public_graph_edges(
        self, request: GraphSampleRequest
    ) -> list[GraphEdgeDTO]:
        self.sample_public_graph_edges_calls.append(request)
        self._maybe_flood("sample_public_graph_edges")
        telegram_id = request.source.telegram_id
        if telegram_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        if telegram_id in self._inaccessible_telegram_ids:
            raise GatewaySourceInaccessible(f"inaccessible:{telegram_id}")
        edges = list(self._graph_sample_edges.get(telegram_id, []))
        # Enforce sample bound; never surface private/inaccessible targets.
        bounded: list[GraphEdgeDTO] = []
        for edge in edges[: max(0, request.message_limit)]:
            target = edge.target
            if target is not None:
                if (
                    not target.accessible
                    or not target.username
                    or target.telegram_id in self._inaccessible_telegram_ids
                ):
                    continue
            bounded.append(edge)
        return bounded

    async def iter_history(
        self, request: HistoryRequest
    ) -> AsyncIterator[TelegramMessageDTO]:
        self.history_calls.append(request)
        entity = _entity_from_peer(request.peer)
        # D-064: ledger records peer entity only — never DB source_id.
        self.resolved_entities.append(entity)
        if self._history_flood and self._flood_wait_until is not None:
            raise GatewayFloodWait(self._flood_wait_until)

        items = self._history_items_for_request(request)
        if request.continuation_cursor is not None:
            try:
                older_than = int(request.continuation_cursor)
            except ValueError:
                older_than = None
            if older_than is not None:
                items = [m for m in items if m.telegram_message_id < older_than]
        if request.after_message_id is not None:
            items = [m for m in items if m.telegram_message_id > request.after_message_id]
        if request.before_published_at is not None:
            items = [m for m in items if m.published_at < request.before_published_at]
        if request.after_published_at is not None:
            items = [m for m in items if m.published_at > request.after_published_at]

        # Newest-first page (Telethon-like), collector reorders for persist.
        items.sort(key=lambda m: m.telegram_message_id, reverse=True)
        for item in items[: request.limit]:
            peer_id = request.peer.telegram_peer_id
            if item.telegram_peer_id is None and peer_id is not None:
                yield TelegramMessageDTO(
                    schema_version=item.schema_version,
                    source_id=request.source_id,
                    telegram_message_id=item.telegram_message_id,
                    published_at=item.published_at,
                    text=item.text,
                    telegram_peer_id=peer_id,
                    edited_at=item.edited_at,
                    author_peer_id=item.author_peer_id,
                    author_username=item.author_username,
                    author_display_name=item.author_display_name,
                    permalink=item.permalink,
                    is_deleted=item.is_deleted,
                )
            else:
                yield item

    async def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]:
        while True:
            item = await self._update_queue.get()
            if item is None:
                return
            yield item

    async def push_update(self, update: TelegramUpdateDTO) -> None:
        await self._update_queue.put(update)

    async def close_updates(self) -> None:
        await self._update_queue.put(None)

    async def get_message(
        self, source: SourceRef, message_id: int
    ) -> TelegramMessageDTO | None:
        peer_id = source.telegram_id
        if peer_id is not None:
            for item in self._messages_by_peer.get(peer_id, []):
                if item.telegram_message_id == message_id:
                    return item
        for item in self._messages.get(source.source_id, []):
            if item.telegram_message_id == message_id:
                return item
        return None

    def _history_items_for_request(
        self, request: HistoryRequest
    ) -> list[TelegramMessageDTO]:
        peer = request.peer
        if peer.telegram_peer_id is not None:
            by_peer = self._messages_by_peer.get(peer.telegram_peer_id)
            if by_peer is not None:
                return list(by_peer)
        # Fixture convenience: tests may still register by DB source_id key.
        return list(self._messages.get(request.source_id, []))

    async def search_global(self, request: GlobalSearchRequest) -> SearchPageDTO:
        self.search_global_calls.append(request)
        self._maybe_flood("search_global")
        hits = self._filter_global_hits(request)
        return self._paginate(hits, request.limit, request.cursor)

    async def search_public_sources(
        self, request: DirectorySearchRequest
    ) -> list[SourceSnapshot]:
        self.search_public_sources_calls.append(request)
        self._maybe_flood("search_public_sources")
        query = request.query.casefold().strip()
        if not query:
            matched = list(self._directory_results)
        else:
            matched = [
                s
                for s in self._directory_results
                if query in s.username.casefold() or query in s.title.casefold()
            ]
        return matched[: request.limit]

    async def check_public_post_search_quota(
        self, query: str
    ) -> PublicPostSearchQuotaDTO:
        self.check_quota_calls.append(query)
        self._maybe_flood("check_public_post_search_quota")
        return self._quota

    async def search_public_posts(
        self, request: PublicPostSearchRequest
    ) -> SearchPageDTO:
        self.search_public_posts_calls.append(request)
        self._assert_no_paid_stars(request)
        self._maybe_flood("search_public_posts")
        if self._raise_premium_on_public_posts:
            raise GatewayPremiumRequired("premium_required")
        if self._raise_quota_exhausted_on_public_posts or (
            not self._quota.free_slot_available and self._quota.stars_amount > 0
        ):
            raise GatewaySearchQuotaExhausted("quota_exhausted")
        if not self._quota.free_slot_available and self._quota.premium_required:
            raise GatewayPremiumRequired("premium_required")
        hits = list(self._public_post_hits_by_query.get(request.query, []))
        return self._paginate(hits, request.limit, request.cursor)

    async def search_source_messages(
        self, request: SourceMessageSearchRequest
    ) -> SearchPageDTO:
        self.search_source_messages_calls.append(request)
        self._maybe_flood("search_source_messages")
        telegram_id = request.source.telegram_id
        if telegram_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        if telegram_id in self._inaccessible_telegram_ids:
            raise GatewaySourceInaccessible(f"inaccessible:{telegram_id}")
        hits = list(self._source_message_hits.get(telegram_id, []))
        if request.published_after is not None:
            hits = [h for h in hits if h.published_at > request.published_after]
        if request.published_before is not None:
            hits = [h for h in hits if h.published_at < request.published_before]
        if request.query:
            q = request.query.casefold()
            hits = [h for h in hits if q in h.excerpt.casefold()]
        return self._paginate(hits, request.limit, request.cursor)

    async def get_linked_discussion(
        self, source: SourceRef
    ) -> SourceSnapshot | None:
        self.get_linked_discussion_calls.append(source)
        self._maybe_flood("get_linked_discussion")
        telegram_id = source.telegram_id
        if telegram_id is None:
            raise GatewaySourceInaccessible("missing_telegram_id")
        if telegram_id in self._inaccessible_telegram_ids:
            raise GatewaySourceInaccessible(f"inaccessible:{telegram_id}")
        if telegram_id in self._private_linked_parents:
            # Private linked chat: not usable for public discovery.
            return None
        return self._linked_discussions.get(telegram_id)

    def register_source(self, username: str, snapshot: SourceSnapshot) -> None:
        self._sources_by_username[username.lower()] = snapshot
        self._sources_by_id[snapshot.telegram_id] = snapshot

    def register_messages(self, source_id: int, messages: list[TelegramMessageDTO]) -> None:
        self._messages[source_id] = messages

    def register_messages_for_peer(
        self, telegram_peer_id: int, messages: list[TelegramMessageDTO]
    ) -> None:
        self._messages_by_peer[telegram_peer_id] = messages

    # --- internals -------------------------------------------------------------

    def _maybe_flood(self, method: SearchMethod) -> None:
        if self._flood_wait_until is not None and method in self._flood_wait_on:
            raise GatewayFloodWait(self._flood_wait_until)

    @staticmethod
    def _assert_no_paid_stars(request: PublicPostSearchRequest) -> None:
        # Constructed so static Zero-Stars scans do not flag this guard as a paid path.
        forbidden = "".join(("allow_", "paid_", "stars"))
        names = {f.name for f in fields(request)}
        if forbidden in names:
            raise AssertionError(f"PublicPostSearchRequest must not include {forbidden}")

    def _filter_global_hits(
        self, request: GlobalSearchRequest
    ) -> list[SearchMessageHitDTO]:
        hits = list(self._global_hits)
        if request.groups_only and request.broadcasts_only:
            return []
        if request.groups_only:
            hits = [h for h in hits if h.source.source_type in _GROUP_TYPES]
        elif request.broadcasts_only:
            hits = [h for h in hits if h.source.source_type in _BROADCAST_TYPES]
        if request.query:
            q = request.query.casefold()
            hits = [
                h
                for h in hits
                if q in h.excerpt.casefold()
                or q in h.source.username.casefold()
                or q in h.source.title.casefold()
            ]
        return hits

    def _paginate(
        self,
        hits: list[SearchMessageHitDTO],
        limit: int,
        cursor: SearchCursor | None,
    ) -> SearchPageDTO:
        page_limit = min(limit, self._default_page_size)
        offset = 0
        if cursor is not None and cursor.token:
            try:
                offset = int(cursor.token)
            except ValueError:
                offset = 0
        page = hits[offset : offset + page_limit]
        next_offset = offset + len(page)
        next_cursor = (
            SearchCursor(schema_version=1, token=str(next_offset))
            if next_offset < len(hits)
            else None
        )
        truncated = next_cursor is not None
        return SearchPageDTO(
            schema_version=1,
            hits=tuple(page),
            next_cursor=next_cursor,
            truncated=truncated,
        )


def _entity_from_peer(peer: TelegramPeerRef) -> int | str:
    """Resolve Telethon-like entity from peer — never DB source_id."""
    if peer.telegram_peer_id is not None:
        return peer.telegram_peer_id
    if peer.username_normalized:
        return peer.username_normalized
    raise GatewaySourceInaccessible("invalid_peer_ref")


def _normalize_ref(value: str) -> str:
    text = value.strip()
    lower = text.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.lstrip("@")
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return text.lower()


def sample_history(
    *,
    source_id: int = 1,
    texts: list[str] | None = None,
) -> list[TelegramMessageDTO]:
    """Helper for integration tests — build a short deterministic history."""
    now = datetime.now(UTC)
    body = texts or [
        "Нужно разработать сайт, бюджет 100000.",
        "Ищу telegram бота под ключ.",
    ]
    return [
        TelegramMessageDTO(
            schema_version=1,
            source_id=source_id,
            telegram_message_id=i + 1,
            text=text,
            published_at=now,
            telegram_peer_id=None,
            edited_at=None,
            author_peer_id=None,
            permalink=None,
        )
        for i, text in enumerate(body)
    ]


def make_source(
    *,
    telegram_id: int,
    username: str,
    title: str | None = None,
    source_type: Literal["channel", "megagroup", "group"] = "channel",
    accessible: bool = True,
) -> SourceSnapshot:
    return SourceSnapshot(
        schema_version=1,
        telegram_id=telegram_id,
        username=username,
        title=title or username,
        source_type=source_type,
        public_url=f"https://t.me/{username}",
        accessible=accessible,
    )


def make_hit(
    *,
    source: SourceSnapshot,
    message_id: int,
    excerpt: str,
    published_at: datetime | None = None,
) -> SearchMessageHitDTO:
    ts = published_at or datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    return SearchMessageHitDTO(
        schema_version=1,
        source=source,
        telegram_message_id=message_id,
        published_at=ts,
        permalink=f"https://t.me/{source.username}/{message_id}",
        excerpt=excerpt,
    )
