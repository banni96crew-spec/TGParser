"""Read-write lock: unlimited shared, graph exclusive with COL-030 wakers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from telegram_lead_discovery.collector.port_parts.errors import GatewayTimeout
from telegram_lead_discovery.collector.port_parts.request_control import GraphCallCancelled


async def _wake_on(event: asyncio.Event, condition: asyncio.Condition) -> None:
    await event.wait()
    async with condition:
        condition.notify_all()


async def _wake_on_timer(
    delay: float, timeout_event: asyncio.Event, condition: asyncio.Condition
) -> None:
    await asyncio.sleep(delay)
    timeout_event.set()
    async with condition:
        condition.notify_all()


async def _await_cancelled(task: asyncio.Task[Any] | None) -> None:
    """Finish a background waker/pulse without replacing the waiter's error."""
    if task is None:
        return
    if not task.done():
        task.cancel()
    # #region agent log
    import json as _json, time as _time
    from pathlib import Path as _Path
    _dbg = _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log")
    try:
        with _dbg.open("a", encoding="utf-8") as _f:
            _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H2","location":"request_lock.py:_await_cancelled","message":"await_pulse_start","data":{"task_done":task.done(),"task_cancelled":task.cancelled()},"timestamp":int(_time.time()*1000)})+"\n")
    except Exception:
        pass
    # #endregion
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except Exception:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError from None
    # #region agent log
    try:
        with _dbg.open("a", encoding="utf-8") as _f:
            _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H2","location":"request_lock.py:_await_cancelled","message":"await_pulse_end","data":{"task_done":task.done()},"timestamp":int(_time.time()*1000)})+"\n")
    except Exception:
        pass
    # #endregion


class AsyncReadWriteLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._writer and self._waiting_writers == 0
            )
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._writer and self._readers == 0
                )
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()

    @asynccontextmanager
    async def exclusive_until(
        self,
        *,
        remaining: float,
        cancel_event: asyncio.Event,
        pulse: Callable[[], Coroutine[Any, Any, None]] | None = None,
        pulse_interval: float = 60.0,
    ) -> AsyncIterator[None]:
        cancel_waker: asyncio.Task[None] | None = None
        timer_waker: asyncio.Task[None] | None = None
        pulse_task: asyncio.Task[None] | None = None
        timeout_event = asyncio.Event()
        try:
            async with self._condition:
                self._waiting_writers += 1
                try:
                    if remaining <= 0:
                        if cancel_event.is_set():
                            raise GraphCallCancelled
                        raise GatewayTimeout
                    cancel_waker = asyncio.create_task(
                        _wake_on(cancel_event, self._condition)
                    )
                    timer_waker = asyncio.create_task(
                        _wake_on_timer(remaining, timeout_event, self._condition)
                    )
                    if pulse is not None:
                        pulse_task = asyncio.create_task(
                            _pulse_until(pulse, pulse_interval, cancel_event, timeout_event)
                        )
                    await self._condition.wait_for(
                        lambda: (not self._writer and self._readers == 0)
                        or cancel_event.is_set()
                        or timeout_event.is_set()
                    )
                    if cancel_event.is_set():
                        raise GraphCallCancelled
                    if timeout_event.is_set():
                        raise GatewayTimeout
                    if not self._writer and self._readers == 0:
                        self._writer = True
                    else:
                        raise GatewayTimeout
                finally:
                    self._waiting_writers -= 1
                    self._condition.notify_all()
                    if cancel_waker is not None:
                        cancel_waker.cancel()
                    if timer_waker is not None:
                        timer_waker.cancel()
                    if pulse_task is not None:
                        pulse_task.cancel()
            try:
                yield
            finally:
                async with self._condition:
                    self._writer = False
                    self._condition.notify_all()
        finally:
            for task in (cancel_waker, timer_waker, pulse_task):
                await _await_cancelled(task)


async def _pulse_until(
    pulse: Callable[[], Coroutine[Any, Any, None]],
    interval: float,
    cancel_event: asyncio.Event,
    timeout_event: asyncio.Event,
) -> None:
    while not cancel_event.is_set() and not timeout_event.is_set():
        try:
            await pulse()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if cancel_event.is_set() or timeout_event.is_set():
            return
        await asyncio.sleep(interval)


__all__ = ["AsyncReadWriteLock"]
