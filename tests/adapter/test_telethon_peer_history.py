"""Adapter tests — TelegramPeerRef resolve / history (COL-023 / D-064)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
    _event_to_update_dto,
)
from telegram_lead_discovery.collector.ports import (
    GatewaySourceInaccessible,
    HistoryRequest,
    SourceRef,
    TelegramPeerRef,
)


class _HistoryClient:
    def __init__(self) -> None:
        self.iter_entities: list[Any] = []
        self.get_entity_calls: list[Any] = []
        self._messages: list[Any] = []

    def set_messages(self, messages: list[Any]) -> None:
        self._messages = messages

    async def get_entity(self, key: Any) -> Any:
        self.get_entity_calls.append(key)
        return SimpleNamespace(id=key if isinstance(key, int) else 55, access_hash=9)

    async def get_input_entity(self, peer_id: int) -> Any:
        from telethon.tl.types import InputPeerChannel

        return InputPeerChannel(channel_id=peer_id, access_hash=1)

    async def iter_messages(self, entity: Any, **kwargs: Any):
        self.iter_entities.append(entity)
        for msg in self._messages:
            yield msg

    async def get_messages(self, entity: Any, ids: int) -> Any:
        self.iter_entities.append(entity)
        for msg in self._messages:
            if int(msg.id) == ids:
                return msg
        return None

    async def disconnect(self) -> None:
        return None


def _msg(mid: int, text: str = "hello") -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        message=text,
        date=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        peer_id=SimpleNamespace(channel_id=777),
    )


@pytest.mark.asyncio
async def test_iter_history_uses_peer_not_source_id() -> None:
    client = _HistoryClient()
    client.set_messages([_msg(1), _msg(2)])
    gw = TelethonTelegramGateway(client=client)
    # Deliberately weird DB source_id that must never reach Telethon.
    request = HistoryRequest(
        schema_version=1,
        source_id=999999,
        peer=TelegramPeerRef(
            schema_version=1,
            telegram_peer_id=777,
            access_hash=42,
            username_normalized="public_chan",
        ),
        limit=10,
        purpose="backfill",
    )
    out = [m async for m in gw.iter_history(request)]
    assert len(out) == 2
    assert all(m.telegram_peer_id == 777 for m in out)
    assert all(m.source_id == 999999 for m in out)
    assert client.iter_entities
    for entity in client.iter_entities:
        # Must not be bare DB source_id.
        assert entity != 999999
        if hasattr(entity, "channel_id"):
            assert int(entity.channel_id) == 777


@pytest.mark.asyncio
async def test_iter_history_resolves_username_peer() -> None:
    client = _HistoryClient()
    client.set_messages([_msg(5, "need site")])
    gw = TelethonTelegramGateway(client=client)
    request = HistoryRequest(
        schema_version=1,
        source_id=3,
        peer=TelegramPeerRef(
            schema_version=1,
            telegram_peer_id=None,
            username_normalized="only_username",
        ),
        limit=5,
    )
    out = [m async for m in gw.iter_history(request)]
    assert len(out) == 1
    assert client.get_entity_calls == ["only_username"]
    assert "only_username" in client.iter_entities or client.iter_entities


@pytest.mark.asyncio
async def test_get_message_never_falls_back_to_source_id() -> None:
    client = _HistoryClient()
    client.set_messages([_msg(9)])
    gw = TelethonTelegramGateway(client=client)
    with pytest.raises(GatewaySourceInaccessible):
        await gw.get_message(
            SourceRef(schema_version=1, source_id=12345, telegram_id=None, username=None),
            9,
        )


def test_event_to_update_dto_stable_identity() -> None:
    event = SimpleNamespace(
        message=SimpleNamespace(
            id=10,
            message="text",
            date=datetime(2026, 7, 2, tzinfo=UTC),
            edit_date=None,
            peer_id=SimpleNamespace(channel_id=55),
        ),
        chat=SimpleNamespace(username="chan"),
        deleted_ids=None,
    )
    dto = _event_to_update_dto(event)
    assert dto is not None
    assert dto.event_type == "message_new"
    assert dto.telegram_peer_id == 55
    assert dto.message is not None
    assert dto.message.telegram_message_id == 10
    assert dto.message.telegram_peer_id == 55


def test_event_to_update_dto_deleted() -> None:
    event = SimpleNamespace(
        message=None,
        deleted_ids=[88],
        peer=SimpleNamespace(channel_id=55),
    )
    dto = _event_to_update_dto(event)
    assert dto is not None
    assert dto.event_type == "message_deleted"
    assert dto.message is not None
    assert dto.message.telegram_message_id == 88
    assert dto.message.is_deleted is True
