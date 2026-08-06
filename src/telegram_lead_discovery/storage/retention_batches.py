"""Shared bounded-batch retention execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


async def purge_batches(
    session: AsyncSession,
    *,
    batch_limit: int,
    purge_once: Callable[..., Awaitable[int]],
) -> int:
    """Continue deletes or updates until a batch returns less than the limit."""
    total = 0
    while True:
        count = await purge_once(session, batch_limit=batch_limit)
        total += count
        if count < batch_limit:
            return total
