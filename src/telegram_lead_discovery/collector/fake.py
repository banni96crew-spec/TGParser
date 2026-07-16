"""In-memory FakeTelegramGateway for tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from telegram_lead_discovery.collector.ports import (
    AccountSnapshot,
    GatewaySourceInaccessible,
    HistoryRequest,
    PublicSourceRef,
    SourceRef,
    SourceSnapshot,
    TelegramMessageDTO,
    TelegramUpdateDTO,
)


class FakeTelegramGateway:
    """Deterministic gateway used by integration tests."""

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
        self.connected = False
        self.history_calls: list[HistoryRequest] = []

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
        key = _normalize_ref(ref.username_or_url)
        snap = self._sources_by_username.get(key)
        if snap is None:
            raise GatewaySourceInaccessible(f"unknown_source:{key}")
        return snap

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot:
        if isinstance(ref, int):
            snap = self._sources_by_id.get(ref)
            if snap is None or not snap.accessible:
                raise GatewaySourceInaccessible(f"inaccessible:{ref}")
            return snap
        return await self.resolve_public_source(ref)

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]:
        return list(self._sources_by_username.values())[:limit]

    async def iter_history(
        self, request: HistoryRequest
    ) -> AsyncIterator[TelegramMessageDTO]:
        self.history_calls.append(request)
        items = list(self._messages.get(request.source_id, []))
        if request.after_message_id is not None:
            items = [m for m in items if m.telegram_message_id > request.after_message_id]
        items.sort(key=lambda m: m.telegram_message_id)
        for item in items[: request.limit]:
            yield item

    async def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]:
        if False:  # pragma: no cover
            yield TelegramUpdateDTO(
                schema_version=1,
                event_type="message_new",
                message=None,
                observed_at=datetime.now(UTC),
            )
        return

    async def get_message(
        self, source: SourceRef, message_id: int
    ) -> TelegramMessageDTO | None:
        for item in self._messages.get(source.source_id, []):
            if item.telegram_message_id == message_id:
                return item
        return None

    def register_source(self, username: str, snapshot: SourceSnapshot) -> None:
        self._sources_by_username[username.lower()] = snapshot
        self._sources_by_id[snapshot.telegram_id] = snapshot

    def register_messages(self, source_id: int, messages: list[TelegramMessageDTO]) -> None:
        self._messages[source_id] = messages


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
            edited_at=None,
            author_peer_id=None,
            permalink=None,
        )
        for i, text in enumerate(body)
    ]
