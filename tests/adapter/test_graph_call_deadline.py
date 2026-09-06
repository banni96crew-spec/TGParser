from __future__ import annotations

import asyncio
import time

import pytest
from telethon.client.users import UserMethods
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import InputPeerEmpty

from telegram_lead_discovery.collector.adapter import controlled_client as controlled_mod
from telegram_lead_discovery.collector.adapter.controlled_client import (
    ControlledTelegramClient,
    _AsyncReadWriteLock,
)
from telegram_lead_discovery.collector.ports import (
    GatewayTimeout,
    GraphCallCancelled,
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
async def test_shared_reader_times_out_graph_call_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controlled_mod, "GRAPH_CALL_DEADLINE_SECONDS", 0.2)

    async def base_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        return "ok"

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    hold = asyncio.Event()

    async def hold_shared() -> None:
        async with client._request_access.shared():
            await hold.wait()

    holder = asyncio.create_task(hold_shared())
    await asyncio.sleep(0)
    controller = GraphRequestController(interval_seconds=0)
    token = current_request_controller.set(controller)
    started = time.monotonic()
    try:
        with pytest.raises(GatewayTimeout):
            await client._call(object(), _history())
        assert time.monotonic() - started <= 1
        assert client._request_access._writer is False
        assert client._request_access._waiting_writers == 0
        assert client._request_retries == 5
        assert client.flood_sleep_threshold == 60
    finally:
        current_request_controller.reset(token)
        hold.set()
        await holder

    assert await client._call(object(), _history()) == "ok"


@pytest.mark.asyncio
async def test_orphan_rpc_that_swallows_cancel_is_not_awaited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controlled_mod, "GRAPH_CALL_DEADLINE_SECONDS", 0.2)
    never = asyncio.Event()

    async def swallow(self, sender, request, ordered=False, flood_sleep_threshold=None):
        try:
            await never.wait()
        except asyncio.CancelledError:
            await never.wait()

    monkeypatch.setattr(UserMethods, "_call", swallow)
    client = _client()
    controller = GraphRequestController(interval_seconds=0)
    token = current_request_controller.set(controller)
    started = time.monotonic()
    try:
        with pytest.raises(GatewayTimeout):
            await client._call(object(), _history())
        assert time.monotonic() - started <= 1
        assert client._request_access._writer is False
        assert client._request_access._waiting_writers == 0
        assert client._request_retries == 5
        assert client.flood_sleep_threshold == 60
    finally:
        current_request_controller.reset(token)


@pytest.mark.asyncio
async def test_cancel_event_during_exclusive_wait_is_not_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def base_call(self, sender, request, ordered=False, flood_sleep_threshold=None):
        raise AssertionError("rpc_started")

    monkeypatch.setattr(UserMethods, "_call", base_call)
    client = _client()
    hold = asyncio.Event()

    async def hold_shared() -> None:
        async with client._request_access.shared():
            await hold.wait()

    holder = asyncio.create_task(hold_shared())
    await asyncio.sleep(0)
    controller = GraphRequestController(interval_seconds=0)
    token = current_request_controller.set(controller)
    try:
        waiter = asyncio.create_task(client._call(object(), _history()))
        await asyncio.sleep(0.05)
        controller.cancel_event.set()
        with pytest.raises(GraphCallCancelled):
            await asyncio.wait_for(waiter, timeout=1)
        assert client._request_access._writer is False
        assert client._request_access._waiting_writers == 0
    finally:
        current_request_controller.reset(token)
        hold.set()
        await holder


async def _failing_heartbeat() -> None:
    raise RuntimeError("heartbeat_failed")


@pytest.mark.asyncio
async def test_failed_heartbeat_does_not_replace_gateway_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controlled_mod, "GRAPH_CALL_DEADLINE_SECONDS", 0.2)
    never = asyncio.Event()

    async def hang(self, sender, request, ordered=False, flood_sleep_threshold=None):
        await never.wait()

    monkeypatch.setattr(UserMethods, "_call", hang)
    client = _client()
    controller = GraphRequestController(
        interval_seconds=0,
        heartbeat=_failing_heartbeat,
        heartbeat_seconds=0.05,
    )
    token = current_request_controller.set(controller)
    try:
        with pytest.raises(GatewayTimeout):
            await asyncio.wait_for(client._call(object(), _history()), timeout=1)
        assert client._request_access._writer is False
        assert client._request_retries == 5
        assert client.flood_sleep_threshold == 60
    finally:
        current_request_controller.reset(token)


@pytest.mark.asyncio
async def test_failed_heartbeat_does_not_replace_graph_call_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom_rpc(self, sender, request, ordered=False, flood_sleep_threshold=None):
        raise AssertionError("rpc_started")

    monkeypatch.setattr(UserMethods, "_call", boom_rpc)
    client = _client()
    hold = asyncio.Event()

    async def hold_shared() -> None:
        async with client._request_access.shared():
            await hold.wait()

    holder = asyncio.create_task(hold_shared())
    await asyncio.sleep(0)
    controller = GraphRequestController(
        interval_seconds=0,
        heartbeat=_failing_heartbeat,
        heartbeat_seconds=0.05,
    )
    token = current_request_controller.set(controller)
    try:
        waiter = asyncio.create_task(client._call(object(), _history()))
        await asyncio.sleep(0.05)
        controller.cancel_event.set()
        with pytest.raises(GraphCallCancelled):
            await asyncio.wait_for(waiter, timeout=1)
        assert client._request_access._writer is False
    finally:
        current_request_controller.reset(token)
        hold.set()
        await holder
