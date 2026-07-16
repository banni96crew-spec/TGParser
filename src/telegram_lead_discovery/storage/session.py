"""Async session write coordinator (STO-002).

Thin helpers used by services/tests; engine ownership lives in `storage.db`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from telegram_lead_discovery.storage import db as storage_db

T = TypeVar("T")

_write_lock = asyncio.Lock()


def configure_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Bind the process-wide session factory to an engine."""
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    storage_db._SESSION_FACTORY = factory  # noqa: SLF001
    storage_db._ENGINE = engine  # noqa: SLF001
    return factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return storage_db.get_session_factory()


async def run_write(fn: Callable[[AsyncSession], Coroutine[Any, Any, T]]) -> T:
    """Serialize writes through a single logical writer."""
    async with _write_lock:
        async with storage_db.session_scope() as session:
            return await fn(session)
