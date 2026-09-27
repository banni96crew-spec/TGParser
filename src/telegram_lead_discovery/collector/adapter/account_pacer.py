"""Durable, account-wide Telegram RPC start gate (D-081 / COL-033)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from telegram_lead_discovery.collector.port_parts.errors import GatewayRateLimited
from telegram_lead_discovery.storage.db import session_scope

_START_INTERVAL = timedelta(seconds=6)
_ROLLING_WINDOW = timedelta(seconds=60)
_MAX_PER_WINDOW = 10


class TelegramAccountPacer:
    """Serializes every physical RPC and durably reserves its start slot."""

    def __init__(self) -> None:
        self._account_lock = asyncio.Lock()

    async def reserve(self, purpose: str) -> None:
        async with self._account_lock:
            await self._reserve_locked(purpose)

    @asynccontextmanager
    async def rpc(self, purpose: str) -> AsyncIterator[None]:
        """Keep the account lock until the raw Telethon call returns or fails."""
        async with self._account_lock:
            await self._reserve_locked(purpose)
            yield

    async def _reserve_locked(self, purpose: str) -> None:
        wall_now = datetime.now(UTC)
        async with session_scope() as session:
            gate = (
                await session.execute(
                    text("SELECT next_allowed_at, flood_wait_until, last_observed_at "
                         "FROM telegram_account_request_gate WHERE id = 1")
                )
            ).mappings().one()
            observed = _as_utc(gate["last_observed_at"])
            now = max(wall_now, observed) if observed else wall_now
            await session.execute(
                text("DELETE FROM telegram_account_request_reservations "
                     "WHERE reserved_at < :cutoff"),
                {"cutoff": now - _ROLLING_WINDOW},
            )
            reservations = (
                await session.execute(
                    text("SELECT reserved_at FROM telegram_account_request_reservations "
                         "ORDER BY reserved_at ASC")
                )
            ).scalars().all()
            candidates = [
                _as_utc(gate["next_allowed_at"]),
                _as_utc(gate["flood_wait_until"]),
            ]
            if len(reservations) >= _MAX_PER_WINDOW:
                candidates.append(_as_utc(reservations[0]) + _ROLLING_WINDOW)
            until = max((item for item in candidates if item is not None), default=now)
            if until > now:
                await session.execute(
                    text("UPDATE telegram_account_request_gate "
                         "SET last_observed_at=:now, version=version+1, updated_at=:now "
                         "WHERE id=1"),
                    {"now": now},
                )
                raise GatewayRateLimited(until)
            await session.execute(
                text("INSERT INTO telegram_account_request_reservations "
                     "(reserved_at, purpose, created_at) VALUES (:now, :purpose, :now)"),
                {"now": now, "purpose": purpose},
            )
            await session.execute(
                text("UPDATE telegram_account_request_gate SET next_allowed_at=:next, "
                     "last_observed_at=:now, version=version+1, updated_at=:now WHERE id=1"),
                {"next": now + _START_INTERVAL, "now": now},
            )


def _as_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


account_pacer = TelegramAccountPacer()
