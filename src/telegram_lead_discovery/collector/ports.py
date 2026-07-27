"""TelegramGateway port and DTOs (D-039)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class PublicSourceRef:
    schema_version: int
    username_or_url: str


@dataclass(frozen=True, slots=True)
class SourceRef:
    schema_version: int
    source_id: int
    telegram_id: int | None = None
    username: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramPeerRef:
    """Network peer identity for Gateway Telegram I/O (COL-023 / D-064).

    DB ``source_id`` MUST NEVER be used as a Telethon entity. At least one of
    ``telegram_peer_id`` or ``username_normalized`` is required.
    """

    schema_version: int
    telegram_peer_id: int | None = None
    access_hash: int | None = None
    username_normalized: str | None = None

    def __post_init__(self) -> None:
        if self.telegram_peer_id is None and not self.username_normalized:
            raise ValueError(
                "TelegramPeerRef requires telegram_peer_id or username_normalized"
            )


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    schema_version: int
    account_id: int
    username: str | None
    connected: bool


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    schema_version: int
    telegram_id: int
    username: str
    title: str
    source_type: Literal["channel", "megagroup", "group"]
    public_url: str | None
    accessible: bool = True


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    schema_version: int
    source_id: int
    peer: TelegramPeerRef
    after_message_id: int | None = None
    after_published_at: datetime | None = None
    before_published_at: datetime | None = None
    limit: int = 100
    purpose: Literal[
        "backfill",
        "startup_reconciliation",
        "periodic_reconciliation",
        "continuation",
    ] = "backfill"
    continuation_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramMessageDTO:
    schema_version: int
    source_id: int
    telegram_message_id: int
    published_at: datetime
    text: str
    telegram_peer_id: int | None = None
    edited_at: datetime | None = None
    author_peer_id: int | None = None
    author_username: str | None = None
    author_display_name: str | None = None
    permalink: str | None = None
    is_deleted: bool = False


@dataclass(frozen=True, slots=True)
class TelegramUpdateDTO:
    schema_version: int
    event_type: Literal["message_new", "message_edited", "message_deleted"]
    message: TelegramMessageDTO | None
    observed_at: datetime
    telegram_peer_id: int | None = None


@dataclass(frozen=True, slots=True)
class SearchCursor:
    schema_version: int
    token: str


@dataclass(frozen=True, slots=True)
class GlobalSearchRequest:
    schema_version: int
    query: str
    groups_only: bool = False
    broadcasts_only: bool = False
    limit: int = 100
    cursor: SearchCursor | None = None


@dataclass(frozen=True, slots=True)
class DirectorySearchRequest:
    schema_version: int
    query: str
    limit: int = 100


@dataclass(frozen=True, slots=True)
class PublicPostSearchRequest:
    """Public post search input. MUST NOT include allow_paid_stars (D-050)."""

    schema_version: int
    query: str
    limit: int = 100
    cursor: SearchCursor | None = None


@dataclass(frozen=True, slots=True)
class SourceMessageSearchRequest:
    schema_version: int
    source: SourceRef
    query: str
    limit: int = 100
    published_after: datetime | None = None
    published_before: datetime | None = None
    cursor: SearchCursor | None = None


@dataclass(frozen=True, slots=True)
class SearchMessageHitDTO:
    schema_version: int
    source: SourceSnapshot
    telegram_message_id: int
    published_at: datetime
    permalink: str | None
    excerpt: str


@dataclass(frozen=True, slots=True)
class SearchPageDTO:
    schema_version: int
    hits: tuple[SearchMessageHitDTO, ...]
    next_cursor: SearchCursor | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class PublicPostSearchQuotaDTO:
    schema_version: int
    free_slot_available: bool
    premium_required: bool
    stars_amount: int


@dataclass(frozen=True, slots=True)
class LinkedDiscussionDTO:
    schema_version: int
    parent_telegram_id: int
    discussion: SourceSnapshot


GraphEdgeType = Literal[
    "recommendation",
    "public_link",
    "mention",
    "forward_origin",
    "linked_discussion",
]


@dataclass(frozen=True, slots=True)
class GraphEdgeDTO:
    """Public-only graph edge discovered from a seed (SRC-042 / SRC-003)."""

    schema_version: int
    edge_type: GraphEdgeType
    seed_telegram_id: int
    raw_reference: str
    normalized_username: str | None = None
    target: SourceSnapshot | None = None
    evidence_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class GraphSampleRequest:
    """Bounded message sample for public_link / mention / forward_origin edges."""

    schema_version: int
    source: SourceRef
    message_limit: int = 50


class GatewayFloodWait(Exception):
    def __init__(self, until: datetime) -> None:
        self.until = until
        super().__init__(f"flood_wait_until={until.isoformat()}")


class GatewayUnauthorized(Exception):
    pass


class GatewayFrozen(Exception):
    pass


class GatewaySourceInaccessible(Exception):
    pass


class GatewayTransientError(Exception):
    pass


class GatewayPermanentError(Exception):
    pass


class GatewayPremiumRequired(Exception):
    pass


class GatewaySearchQuotaExhausted(Exception):
    pass


class GatewayInvalidSearchQuery(Exception):
    pass


class GatewaySearchUnavailable(Exception):
    pass


class TelegramGateway(Protocol):
    async def connect(self) -> AccountSnapshot: ...

    async def disconnect(self) -> None: ...

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot: ...

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot: ...

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]: ...

    def iter_history(
        self, request: HistoryRequest
    ) -> AsyncIterator[TelegramMessageDTO]: ...

    def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]: ...

    async def get_message(
        self, source: SourceRef, message_id: int
    ) -> TelegramMessageDTO | None: ...

    async def search_global(self, request: GlobalSearchRequest) -> SearchPageDTO: ...

    async def search_public_sources(
        self, request: DirectorySearchRequest
    ) -> list[SourceSnapshot]: ...

    async def check_public_post_search_quota(
        self, query: str
    ) -> PublicPostSearchQuotaDTO: ...

    async def search_public_posts(
        self, request: PublicPostSearchRequest
    ) -> SearchPageDTO: ...

    async def search_source_messages(
        self, request: SourceMessageSearchRequest
    ) -> SearchPageDTO: ...

    async def get_linked_discussion(
        self, source: SourceRef
    ) -> SourceSnapshot | None: ...

    async def sample_public_graph_edges(
        self, request: GraphSampleRequest
    ) -> list[GraphEdgeDTO]: ...
