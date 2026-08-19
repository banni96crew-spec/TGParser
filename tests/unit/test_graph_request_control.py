from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.collector.ports import (
    NestedTelegramRequest,
    RequestBudgetExhausted,
    UnsupportedBatchRequest,
)
from telegram_lead_discovery.source_discovery.graph_request_control import (
    GraphRequestController,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.wall = datetime(2026, 1, 1, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def wall_clock(self) -> datetime:
        return self.wall + timedelta(seconds=self.value)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


async def _request(controller: GraphRequestController, marker: object | None = None) -> None:
    await controller.before_request(marker or object())
    await controller.after_request()


@pytest.mark.asyncio
async def test_first_request_immediate_then_six_seconds_and_semi_open_window() -> None:
    clock = FakeClock()
    reservations: list[dict[str, object]] = []

    async def persist(value: dict[str, object]) -> None:
        reservations.append(value)

    controller = GraphRequestController(
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=clock.sleep,
        persist_reservation=persist,
    )
    moments: list[float] = []
    for _ in range(11):
        await _request(controller)
        moments.append(clock.value)

    assert moments == [0.0, 6.0, 12.0, 18.0, 24.0, 30.0, 36.0, 42.0, 48.0, 54.0, 60.0]
    assert reservations[-1]["reserved_total"] == 11
    assert len(reservations[-1]["rolling_reservations_utc"]) == 10


@pytest.mark.asyncio
async def test_request_cap_rejects_next_request_before_persist() -> None:
    clock = FakeClock()
    persisted: list[dict[str, object]] = []

    async def persist(value: dict[str, object]) -> None:
        persisted.append(value)

    controller = GraphRequestController(
        request_cap=200,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=clock.sleep,
        persist_reservation=persist,
    )
    for _ in range(200):
        await _request(controller)
    with pytest.raises(RequestBudgetExhausted):
        await controller.before_request(object())
    assert len(persisted) == 200


@pytest.mark.asyncio
async def test_restart_with_prior_reservation_waits_full_window() -> None:
    clock = FakeClock()
    controller = GraphRequestController(
        reserved_total=1,
        monotonic=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=clock.sleep,
    )
    await _request(controller)
    assert clock.sleeps == [60.0]
    assert clock.value == 60.0


@pytest.mark.asyncio
async def test_batch_and_same_task_nested_request_are_rejected() -> None:
    controller = GraphRequestController()
    with pytest.raises(UnsupportedBatchRequest):
        await controller.before_request([object()])
    await controller.before_request(object())
    with pytest.raises(NestedTelegramRequest):
        await controller.before_request(object())
    await controller.after_request()


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized() -> None:
    entered: list[int] = []
    release = asyncio.Event()
    controller = GraphRequestController(interval_seconds=0, window_limit=10)

    async def run(number: int) -> None:
        await controller.before_request(object())
        entered.append(number)
        if number == 1:
            await release.wait()
        await controller.after_request()

    first = asyncio.create_task(run(1))
    await asyncio.sleep(0)
    second = asyncio.create_task(run(2))
    await asyncio.sleep(0)
    assert entered == [1]
    release.set()
    await asyncio.gather(first, second)
    assert entered == [1, 2]


@pytest.mark.asyncio
async def test_failed_persistence_does_not_consume_in_memory_reservation() -> None:
    async def fail(_value: dict[str, object]) -> None:
        raise RuntimeError("storage_failed")

    controller = GraphRequestController(persist_reservation=fail)
    with pytest.raises(RuntimeError, match="storage_failed"):
        await controller.before_request(object())
    assert controller.reserved_total == 0
    assert controller.snapshot()["rolling_reservations_utc"] == []
