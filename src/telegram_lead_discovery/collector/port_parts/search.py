from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from telegram_lead_discovery.collector.port_parts.sources import (
    SourceRef,
    SourceSnapshot,
)


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
