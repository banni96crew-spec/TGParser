"""Neutral per-context control for Telegram requests."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Protocol

GRAPH_CALL_DEADLINE_SECONDS = 30.0


class RequestControlError(RuntimeError):
    """Base error for graph-only request control."""


class GraphCallCancelled(RequestControlError):
    """Graph call interrupted by CancelGraphDiscoveryRun (not GatewayTimeout)."""


class RequestBudgetExhausted(RequestControlError):
    """The graph crawl has reserved its maximum request count."""


class UnsupportedBatchRequest(RequestControlError):
    """A graph request attempted to send a Telethon batch."""


class NestedTelegramRequest(RequestControlError):
    """A graph request attempted another Telegram request before completion."""


class TelegramRequestController(Protocol):
    cancel_event: asyncio.Event

    async def before_request(self, request: Any) -> None: ...

    async def after_request(self) -> None: ...


current_request_controller: ContextVar[TelegramRequestController | None] = ContextVar(
    "current_request_controller",
    default=None,
)


__all__ = [
    "GRAPH_CALL_DEADLINE_SECONDS",
    "GraphCallCancelled",
    "NestedTelegramRequest",
    "RequestBudgetExhausted",
    "RequestControlError",
    "TelegramRequestController",
    "UnsupportedBatchRequest",
    "current_request_controller",
]
