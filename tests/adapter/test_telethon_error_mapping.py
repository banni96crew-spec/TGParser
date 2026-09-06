"""COL-012 — Telethon permanent access codes map to GatewaySourceInaccessible."""

from __future__ import annotations

from telethon import errors as te

from telegram_lead_discovery.collector.adapter.telethon_parts.error_mapping import (
    _map_telethon_error,
)
from telegram_lead_discovery.collector.ports import (
    GatewayPermanentError,
    GatewaySourceInaccessible,
)


def _rpc(*, code: int, message: str) -> te.RPCError:
    return te.RPCError(request=None, message=message, code=code)


def test_username_not_occupied_is_source_inaccessible() -> None:
    mapped = _map_telethon_error(te.UsernameNotOccupiedError(request=None))
    assert isinstance(mapped, GatewaySourceInaccessible)
    assert not isinstance(mapped, GatewayPermanentError)


def test_channel_invalid_is_source_inaccessible() -> None:
    mapped = _map_telethon_error(te.ChannelInvalidError(request=None))
    assert isinstance(mapped, GatewaySourceInaccessible)


def test_username_not_occupied_message_is_source_inaccessible() -> None:
    mapped = _map_telethon_error(_rpc(code=400, message="USERNAME_NOT_OCCUPIED"))
    assert isinstance(mapped, GatewaySourceInaccessible)
    mapped = _map_telethon_error(_rpc(code=400, message="PEER_ID_INVALID"))
    assert isinstance(mapped, GatewayPermanentError)
