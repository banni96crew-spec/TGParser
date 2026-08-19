"""Neutral per-context control for Telegram requests."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Protocol


class RequestControlError(RuntimeError):
    """Base error for graph-only request control."""


class RequestBudgetExhausted(RequestControlError):
    """The graph crawl has reserved its maximum request count."""


class UnsupportedBatchRequest(RequestControlError):
    """A graph request attempted to send a Telethon batch."""


class NestedTelegramRequest(RequestControlError):
    """A graph request attempted another Telegram request before completion."""


class TelegramRequestController(Protocol):
    async def before_request(self, request: Any) -> None: ...

    async def after_request(self) -> None: ...


current_request_controller: ContextVar[TelegramRequestController | None] = ContextVar(
    "current_request_controller",
    default=None,
)


__all__ = [
    "NestedTelegramRequest",
    "RequestBudgetExhausted",
    "RequestControlError",
    "TelegramRequestController",
    "UnsupportedBatchRequest",
    "current_request_controller",
]
