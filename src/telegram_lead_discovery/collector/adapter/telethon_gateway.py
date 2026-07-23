"""Telethon-only TelegramGateway adapter (COL)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from telegram_lead_discovery.collector.ports import (
    AccountSnapshot,
    GatewayPermanentError,
    GatewayTransientError,
    HistoryRequest,
    PublicSourceRef,
    SourceRef,
    SourceSnapshot,
    TelegramMessageDTO,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.security.secrets import load_secret_presence
from telegram_lead_discovery.security.session_paths import session_path


class TelethonTelegramGateway:
    """Thin Telethon adapter. Connect may stub when session/secrets are absent."""

    def __init__(self) -> None:
        self._client = None
        self._connected = False

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
            raise GatewayTransientError(str(exc)) from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self._client = None
        self._connected = False

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot:
        if self._client is None:
            raise GatewayPermanentError("gateway_not_connected")

        entity = await self._client.get_entity(ref.username_or_url)
        return _entity_to_snapshot(entity)

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot:
        if self._client is None:
            raise GatewayPermanentError("gateway_not_connected")
        entity = await self._client.get_entity(ref if isinstance(ref, int) else ref.username_or_url)
        return _entity_to_snapshot(entity)

    async def get_recommendations(
        self, source: SourceRef, limit: int
    ) -> list[SourceSnapshot]:
        return []

    async def iter_history(
        self, request: HistoryRequest
    ) -> AsyncIterator[TelegramMessageDTO]:
        if self._client is None:
            return
            yield  # pragma: no cover
        from telethon.tl.custom.message import Message  # noqa: F401 — type hint only

        entity = request.source_id
        async for message in self._client.iter_messages(
            entity,
            limit=request.limit,
            min_id=request.after_message_id or 0,
        ):
            yield TelegramMessageDTO(
                schema_version=1,
                source_id=request.source_id,
                telegram_message_id=int(message.id),
                published_at=message.date.replace(tzinfo=UTC)
                if message.date.tzinfo is None
                else message.date,
                text=message.message or "",
                edited_at=None,
                author_peer_id=None,
                permalink=None,
            )

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
        if self._client is None:
            return None
        message = await self._client.get_messages(
            source.telegram_id or source.source_id, ids=message_id
        )
        if message is None:
            return None
        return TelegramMessageDTO(
            schema_version=1,
            source_id=source.source_id,
            telegram_message_id=int(message.id),
            published_at=message.date.replace(tzinfo=UTC)
            if message.date.tzinfo is None
            else message.date,
            text=message.message or "",
        )


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
