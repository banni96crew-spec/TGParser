from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
    """Network peer identity for Gateway Telegram I/O (COL-023 / D-064)."""

    schema_version: int
    telegram_peer_id: int | None = None
    access_hash: int | None = None
    username_normalized: str | None = None

    def __post_init__(self) -> None:
        if self.telegram_peer_id is None and not self.username_normalized:
            raise ValueError("TelegramPeerRef requires telegram_peer_id or username_normalized")


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
