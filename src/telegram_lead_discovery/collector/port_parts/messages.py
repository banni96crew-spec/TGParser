from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from telegram_lead_discovery.collector.port_parts.sources import TelegramPeerRef


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
        "scouting_verification",
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
