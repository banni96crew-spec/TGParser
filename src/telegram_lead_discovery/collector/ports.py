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
    after_message_id: int | None = None
    after_published_at: datetime | None = None
    before_published_at: datetime | None = None
    limit: int = 100
    purpose: Literal["backfill", "startup_reconciliation", "periodic_reconciliation"] = "backfill"


@dataclass(frozen=True, slots=True)
class TelegramMessageDTO:
    schema_version: int
    source_id: int
    telegram_message_id: int
    published_at: datetime
    text: str
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
