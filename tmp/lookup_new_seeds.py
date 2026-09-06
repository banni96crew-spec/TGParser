"""Lookup owner seeds in SQLite. Graph-only helper."""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from telegram_lead_discovery.source_discovery.graph_edges import is_private_invite_ref
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope
from telegram_lead_discovery.storage.models import TelegramSource

SEEDS = [
    "https://t.me/python_chatt",
    "https://t.me/+R_KxUQG5hYo5ZjAy",
    "https://t.me/freelancerscha",
    "https://t.me/frilans_na_legke",
    "https://t.me/digitaltender",
    "https://t.me/TRemoters",
]


async def main() -> None:
    await init_engine(database_path())
    async with session_scope() as session:
        active = (
            await session.execute(
                text(
                    "SELECT id, run_type, state FROM discovery_runs "
                    "WHERE state IN ('queued','running','cancelling',"
                    "'retry_wait_flood')"
                )
            )
        ).fetchall()
        print(f"active={active}", flush=True)
        for raw in SEEDS:
            if is_private_invite_ref(raw):
                print(f"{raw}: private_invite", flush=True)
                continue
            try:
                username = normalize_username(raw)
            except InvalidUsernameError as exc:
                print(f"{raw}: {exc}", flush=True)
                continue
            row = (
                await session.execute(
                    select(TelegramSource).where(
                        TelegramSource.username_normalized == username
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                print(f"{raw} ({username}): NOT_IN_DB", flush=True)
            else:
                print(
                    f"{raw} ({username}): id={row.id} tg={row.telegram_id} "
                    f"state={row.lifecycle_state}",
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(main())
