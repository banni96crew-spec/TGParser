"""Telethon client with graph-only request isolation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from telethon import TelegramClient

from telegram_lead_discovery.collector.ports import current_request_controller


class _AsyncReadWriteLock:
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


class ControlledTelegramClient(TelegramClient):
    """Apply strict limits only when a graph controller is in context."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._request_access = _AsyncReadWriteLock()

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

        await controller.before_request(request)
        try:
            async with self._request_access.exclusive():
                previous_retries = self._request_retries
                previous_threshold = self.flood_sleep_threshold
                self._request_retries = 0
                self.flood_sleep_threshold = 0
                try:
                    return await super()._call(
                        sender,
                        request,
                        ordered=ordered,
                        flood_sleep_threshold=0,
                    )
                finally:
                    self._request_retries = previous_retries
                    self.flood_sleep_threshold = previous_threshold
        finally:
            await controller.after_request()


__all__ = ["ControlledTelegramClient"]
