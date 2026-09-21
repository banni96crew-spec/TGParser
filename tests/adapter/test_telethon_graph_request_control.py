from __future__ import annotations

import asyncio
from typing import Any

import pytest
from telethon import errors as telethon_errors
from telethon.client.users import UserMethods
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerChannel, InputPeerEmpty

from telegram_lead_discovery.collector.adapter.controlled_client import (
    ControlledTelegramClient,
    _AsyncReadWriteLock,
)
from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GraphSampleRequest,
    NestedTelegramRequest,
    SourceRef,
    UnsupportedBatchRequest,
    current_request_controller,
)
from telegram_lead_discovery.source_discovery.graph_request_control import (
    GraphRequestController,
)


def _client() -> ControlledTelegramClient:
    client = object.__new__(ControlledTelegramClient)
    client._request_access = _AsyncReadWriteLock()
    client._request_retries = 5
    client._flood_sleep_threshold = 60
    return client


def _history() -> GetHistoryRequest:
    return GetHistoryRequest(
        peer=InputPeerEmpty(),
        offset_id=0,
        offset_date=None,
        add_offset=0,
        limit=100,
        max_id=0,
        min_id=0,
        hash=0,
    )


@pytest.mark.asyncio
async def test_graph_call_uses_one_sender_call_and_restores_client_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Any, int, int]] = []

    async def base_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        seen.append((request, self._request_retries, self.flood_sleep_threshold))
        return "ok"

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    controller = GraphRequestController(interval_seconds=0)
    token = current_request_controller.set(controller)
    try:
        result = await client._call(object(), _history())
    finally:
        current_request_controller.reset(token)

    assert result == "ok"
    assert len(seen) == 1
    assert seen[0][1:] == (0, 0)
    assert client._request_retries == 5
    assert client.flood_sleep_threshold == 60


@pytest.mark.asyncio
async def test_graph_batch_is_rejected_before_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def base_call(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    token = current_request_controller.set(GraphRequestController(interval_seconds=0))
    try:
        with pytest.raises(UnsupportedBatchRequest):
            await client._call(object(), [_history()])
    finally:
        current_request_controller.reset(token)
    assert called is False


@pytest.mark.asyncio
async def test_non_graph_call_keeps_existing_retry_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int, int]] = []

    async def base_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        seen.append((self._request_retries, self.flood_sleep_threshold))
        return "ordinary"

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    assert await client._call(object(), _history()) == "ordinary"
    assert seen == [(5, 60)]


@pytest.mark.asyncio
async def test_graph_call_restores_settings_after_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def base_call(*args, **kwargs):
        raise RuntimeError("sender_failed")

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    token = current_request_controller.set(GraphRequestController(interval_seconds=0))
    try:
        with pytest.raises(RuntimeError, match="sender_failed"):
            await client._call(object(), _history())
    finally:
        current_request_controller.reset(token)
    assert client._request_retries == 5
    assert client.flood_sleep_threshold == 60


@pytest.mark.asyncio
async def test_nested_client_call_is_rejected_and_outer_lock_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def nested_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        nonlocal calls
        calls += 1
        return await self._call(sender, _history())

    monkeypatch.setattr(UserMethods, "_call", nested_call)
    client = _client()
    token = current_request_controller.set(GraphRequestController(interval_seconds=0))
    try:
        with pytest.raises(NestedTelegramRequest):
            await client._call(object(), _history())
    finally:
        current_request_controller.reset(token)
    assert calls == 1
    assert client._request_access._writer is False
    assert client._request_retries == 5
    assert client.flood_sleep_threshold == 60


@pytest.mark.asyncio
async def test_cancelled_shared_waiter_does_not_corrupt_request_lock() -> None:
    lock = _AsyncReadWriteLock()
    entered = False

    async def wait_shared() -> None:
        nonlocal entered
        async with lock.shared():
            entered = True

    async with lock.exclusive():
        waiter = asyncio.create_task(wait_shared())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    async with lock.shared():
        entered = True
    assert entered is True


@pytest.mark.asyncio
async def test_reentrant_shared_call_completes_while_writer_is_waiting() -> None:
    lock = _AsyncReadWriteLock()
    writer_entered = asyncio.Event()

    async def writer() -> None:
        async with lock.exclusive():
            writer_entered.set()

    async with lock.shared():
        writer_task = asyncio.create_task(writer())
        while lock._waiting_writers == 0:
            await asyncio.sleep(0)
        async with asyncio.timeout(0.2):
            async with lock.shared():
                assert lock._readers == 1

    await asyncio.wait_for(writer_task, timeout=0.2)
    assert writer_entered.is_set()
    assert lock._readers == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: telethon_errors.FloodWaitError(None, 7),
        lambda: telethon_errors.FloodPremiumWaitError(None, 7),
        lambda: telethon_errors.FloodTestPhoneWaitError(None, 7),
        lambda: telethon_errors.SlowModeWaitError(None, 7),
        lambda: telethon_errors.PeerFloodError(None),
    ],
)
async def test_all_flood_variants_stop_after_one_controlled_sender_call(
    monkeypatch: pytest.MonkeyPatch,
    error_factory,
) -> None:
    calls = 0

    async def raise_flood(self, sender, request, ordered=False, flood_sleep_threshold=None):
        nonlocal calls
        calls += 1
        raise error_factory()

    monkeypatch.setattr(UserMethods, "_call", raise_flood)
    client = _client()
    client.session = _OfflineSession()
    client._sender = object()
    gateway = TelethonTelegramGateway(client=client)
    controller = GraphRequestController(interval_seconds=0)
    token = current_request_controller.set(controller)
    try:
        with pytest.raises(GatewayFloodWait):
            await gateway.get_recommendations(
                SourceRef(
                    schema_version=1,
                    source_id=1,
                    telegram_id=123,
                    username="cached_source",
                    access_hash=456,
                ),
                25,
            )
    finally:
        current_request_controller.reset(token)
    assert calls == 1
    assert controller.reserved_total == 1
    assert client._request_retries == 5
    assert client.flood_sleep_threshold == 60


class _OfflineSession:
    def get_input_entity(self, key):
        if key in {123, "cached_source"}:
            return InputPeerChannel(channel_id=123, access_hash=456)
        raise ValueError("not_cached")


class _RawClient:
    def __init__(self) -> None:
        self.session = _OfflineSession()
        self.calls: list[Any] = []

    async def __call__(self, request):
        self.calls.append(request)
        return type("HistoryResult", (), {"messages": [], "chats": []})()

    async def get_entity(self, key):
        raise AssertionError(f"high_level_get_entity_used:{key}")

    async def get_messages(self, *args, **kwargs):
        raise AssertionError("high_level_get_messages_used")


@pytest.mark.asyncio
async def test_offline_session_resolution_uses_no_network() -> None:
    client = _RawClient()
    gateway = TelethonTelegramGateway(client=client)
    snapshot = await gateway.resolve_graph_source(
        SourceRef(
            schema_version=1,
            source_id=1,
            telegram_id=123,
            username="cached_source",
        )
    )
    assert snapshot.telegram_id == 123
    assert snapshot.access_hash == 456
    assert client.calls == []


@pytest.mark.asyncio
async def test_graph_history_is_one_raw_request_with_limit_100() -> None:
    client = _RawClient()
    gateway = TelethonTelegramGateway(client=client)
    edges = await gateway.sample_public_graph_edges(
        GraphSampleRequest(
            schema_version=1,
            source=SourceRef(
                schema_version=1,
                source_id=1,
                telegram_id=123,
                username="cached_source",
                access_hash=456,
            ),
            message_limit=100,
        )
    )
    assert edges == []
    assert len(client.calls) == 1
    assert isinstance(client.calls[0], GetHistoryRequest)
    assert client.calls[0].limit == 100
