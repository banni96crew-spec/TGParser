"""Strict request limiter for one graph discovery run."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from telegram_lead_discovery.collector.ports import (
    NestedTelegramRequest,
    RequestBudgetExhausted,
    UnsupportedBatchRequest,
)

PersistReservation = Callable[[dict[str, Any]], Awaitable[None]]


class GraphRequestController:
    """6-second spacing, rolling 10/minute, and 200/run hard cap."""

    def __init__(
        self,
        *,
        reserved_total: int = 0,
        persist_reservation: PersistReservation | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], datetime] | None = None,
        interval_seconds: float = 6.0,
        window_seconds: float = 60.0,
        window_limit: int = 10,
        request_cap: int = 200,
    ) -> None:
        self.reserved_total = max(0, int(reserved_total))
        self._persist = persist_reservation
        self._monotonic = monotonic
        self._sleep = sleeper
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._interval = interval_seconds
        self._window = window_seconds
        self._window_limit = window_limit
        self._request_cap = request_cap
        self._reservations: deque[float] = deque()
        self._reservation_times_utc: deque[str] = deque(maxlen=window_limit)
        self._last_monotonic: float | None = None
        self._last_request_at_utc: str | None = None
        self._restart_cooldown = self.reserved_total > 0
        self._operation_lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "reserved_total": self.reserved_total,
            "last_request_at_utc": self._last_request_at_utc,
            "rolling_reservations_utc": list(self._reservation_times_utc),
        }

    async def before_request(self, request: Any) -> None:
        if isinstance(request, list | tuple):
            raise UnsupportedBatchRequest("graph_batch_request_not_supported")
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            raise NestedTelegramRequest("nested_graph_telegram_request")
        await self._operation_lock.acquire()
        self._owner = task
        try:
            if self.reserved_total >= self._request_cap:
                raise RequestBudgetExhausted(
                    f"graph_request_cap_reached:{self._request_cap}"
                )
            if self._restart_cooldown:
                await self._sleep(self._window)
                self._restart_cooldown = False
                self._reservations.clear()
                self._last_monotonic = None
            await self._wait_for_slot()
            now_mono = self._monotonic()
            now_utc = self._wall_clock().astimezone(UTC).isoformat()
            next_total = self.reserved_total + 1
            snapshot = {
                "reserved_total": next_total,
                "last_request_at_utc": now_utc,
                "rolling_reservations_utc": [
                    *self._reservation_times_utc,
                    now_utc,
                ][-self._window_limit :],
            }
            if self._persist is not None:
                await self._persist(snapshot)
            self.reserved_total = next_total
            self._last_monotonic = now_mono
            self._last_request_at_utc = now_utc
            self._reservations.append(now_mono)
            self._reservation_times_utc.append(now_utc)
        except BaseException:
            self._owner = None
            self._operation_lock.release()
            raise

    async def after_request(self) -> None:
        if self._operation_lock.locked():
            self._owner = None
            self._operation_lock.release()

    async def _wait_for_slot(self) -> None:
        while True:
            now = self._monotonic()
            while self._reservations and self._reservations[0] <= now - self._window:
                self._reservations.popleft()
            target = now
            if self._last_monotonic is not None:
                target = max(target, self._last_monotonic + self._interval)
            if len(self._reservations) >= self._window_limit:
                target = max(target, self._reservations[0] + self._window)
            delay = target - now
            if delay <= 0:
                return
            await self._sleep(delay)


__all__ = ["GraphRequestController"]
