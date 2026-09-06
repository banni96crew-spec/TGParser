"""Inspect seeds and discovery state for live graph run."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select, text

from telegram_lead_discovery.infrastructure.paths import database_path, lock_path
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.db import init_engine, session_scope
from telegram_lead_discovery.storage.models import TelegramSource

SEED_REFS = [
    "@workk_onchat",
    "@designer_jobs",
    "@GetClient",
    "@program_job",
    "https://t.me/+R_KxUQG5hYo5ZjAy",
    "@poiskfreelance",
    "@mari_vakansii",
    "@freelance_chatik0",
    "@freelancerscha",
    "@rueventjob4at",
]


async def main() -> None:
    await init_engine(database_path())
    print("lock", lock_path().exists())
    async with session_scope() as session:
        active = await session.execute(
            text(
                "SELECT id, run_type, state, phase FROM discovery_runs "
                "WHERE state IN ('queued','running','cancelling','retry_wait_flood')"
            )
        )
        print("active runs", active.fetchall())
        recent = await session.execute(
            text(
                "SELECT id, run_type, state, phase, counters_json, last_error_code "
                "FROM discovery_runs ORDER BY id DESC LIMIT 3"
            )
        )
        print("recent runs:")
        for row in recent:
            print(row)

        for raw in SEED_REFS:
            try:
                username = normalize_username(raw)
            except InvalidUsernameError:
                print(f"{raw}: non-username ref")
                continue
            row = (
                await session.execute(
                    select(TelegramSource).where(
                        TelegramSource.username_normalized == username
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                print(f"{raw} ({username}): NOT IN DB")
            else:
                print(
                    f"{raw} ({username}): id={row.id} tg={row.telegram_id} "
                    f"hash={row.access_hash} state={row.lifecycle_state}"
                )


if __name__ == "__main__":
    asyncio.run(main())
