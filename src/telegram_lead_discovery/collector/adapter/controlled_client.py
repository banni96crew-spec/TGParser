"""Telethon client with graph-only request isolation (COL-028 / COL-030)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from telethon import TelegramClient

from telegram_lead_discovery.collector.adapter.request_lock import (
    AsyncReadWriteLock,
    _await_cancelled,
)
from telegram_lead_discovery.collector.ports import (
    GRAPH_CALL_DEADLINE_SECONDS,
    GatewayTimeout,
    GraphCallCancelled,
    NestedTelegramRequest,
    current_request_controller,
)

# Tests import the historical private name.
_AsyncReadWriteLock = AsyncReadWriteLock


def _abandon_rpc(task: asyncio.Task[Any]) -> None:
    def _consume(done: asyncio.Task[Any]) -> None:
        if done.cancelled():
            return
        done.exception()

    task.add_done_callback(_consume)


async def _pulse_rpc(
    pulse: Any,
    cancel_event: asyncio.Event,
    interval: float,
) -> None:
    if pulse is None or not callable(pulse):
        return
    while not cancel_event.is_set():
        try:
            await pulse()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if cancel_event.is_set():
            return
        await asyncio.sleep(interval)


async def _wait_graph_rpc(
    rpc_task: asyncio.Task[Any],
    cancel_event: asyncio.Event,
    remaining: float,
    *,
    pulse: Any = None,
    pulse_interval: float = 60.0,
) -> Any:
    cancel_wait = asyncio.create_task(cancel_event.wait())
    pulse_task = asyncio.create_task(
        _pulse_rpc(pulse, cancel_event, pulse_interval)
    )
    try:
        done, pending = await asyncio.wait(
            {rpc_task, cancel_wait},
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_wait in pending:
            cancel_wait.cancel()
            try:
                await cancel_wait
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
        if cancel_event.is_set() and rpc_task not in done:
            _abandon_rpc(rpc_task)
            raise GraphCallCancelled
        if rpc_task in done:
            # #region agent log
            import json as _json, time as _time
            from pathlib import Path as _Path
            _exc = None if not rpc_task.cancelled() else "CancelledError"
            if _exc is None and rpc_task.exception() is not None:
                _exc = type(rpc_task.exception()).__name__
            try:
                with _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log").open(
                    "a", encoding="utf-8"
                ) as _f:
                    _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H1","location":"controlled_client.py:_wait_graph_rpc","message":"rpc_done","data":{"cancelled":rpc_task.cancelled(),"exc":_exc,"cancel_set":cancel_event.is_set()},"timestamp":int(_time.time()*1000)})+"\n")
            except Exception:
                pass
            # #endregion
            return rpc_task.result()
        # #region agent log
        import json as _json, time as _time
        from pathlib import Path as _Path
        try:
            with _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log").open(
                "a", encoding="utf-8"
            ) as _f:
                _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H4","location":"controlled_client.py:_wait_graph_rpc","message":"raise_gateway_timeout","data":{"rpc_done":rpc_task.done(),"remaining":remaining},"timestamp":int(_time.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
        _abandon_rpc(rpc_task)
        raise GatewayTimeout
    except BaseException:
        if not rpc_task.done():
            _abandon_rpc(rpc_task)
        raise
    finally:
        await _await_cancelled(pulse_task)


class ControlledTelegramClient(TelegramClient):
    """Apply strict limits only when a graph controller is in context."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._request_access = AsyncReadWriteLock()

    async def _call(
        self,
        sender: Any,
        request: Any,
        ordered: bool = False,
        flood_sleep_threshold: int | None = None,
    ) -> Any:
        controller = current_request_controller.get()
        if controller is None:
            async with self._request_access.shared():
                return await super()._call(
                    sender,
                    request,
                    ordered=ordered,
                    flood_sleep_threshold=flood_sleep_threshold,
                )

        rpc_tasks = getattr(self, "_graph_rpc_tasks", None)
        if rpc_tasks is not None and asyncio.current_task() in rpc_tasks:
            raise NestedTelegramRequest("nested_graph_telegram_request")

        await controller.before_request(request)
        try:
            return await self._graph_call(
                controller, sender, request, ordered=ordered
            )
        finally:
            await controller.after_request()

    async def _graph_call(
        self,
        controller: Any,
        sender: Any,
        request: Any,
        *,
        ordered: bool,
    ) -> Any:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + GRAPH_CALL_DEADLINE_SECONDS
        cancel_event = getattr(controller, "cancel_event", None) or asyncio.Event()
        pulse = getattr(controller, "pulse", None)
        remaining = deadline - loop.time()
        pulse_interval = float(getattr(controller, "_heartbeat_seconds", 60.0))
        async with self._request_access.exclusive_until(
            remaining=remaining,
            cancel_event=cancel_event,
            pulse=pulse if callable(pulse) else None,
            pulse_interval=pulse_interval,
        ):
            remaining = deadline - loop.time()
            if remaining <= 0:
                if cancel_event.is_set():
                    raise GraphCallCancelled
                raise GatewayTimeout
            previous_retries = self._request_retries
            previous_threshold = self.flood_sleep_threshold
            self._request_retries = 0
            self.flood_sleep_threshold = 0
            rpc_tasks = getattr(self, "_graph_rpc_tasks", None)
            if rpc_tasks is None:
                rpc_tasks = set()
                self._graph_rpc_tasks = rpc_tasks
            try:
                rpc_task = asyncio.create_task(
                    super()._call(
                        sender,
                        request,
                        ordered=ordered,
                        flood_sleep_threshold=0,
                    )
                )
                rpc_tasks.add(rpc_task)
                rpc_task.add_done_callback(rpc_tasks.discard)
                return await _wait_graph_rpc(
                    rpc_task,
                    cancel_event,
                    remaining,
                    pulse=pulse if callable(pulse) else None,
                    pulse_interval=pulse_interval,
                )
            finally:
                self._request_retries = previous_retries
                self.flood_sleep_threshold = previous_threshold


__all__ = ["ControlledTelegramClient", "_AsyncReadWriteLock"]
