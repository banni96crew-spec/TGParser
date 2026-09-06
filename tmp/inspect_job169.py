"""Inspect job 169 and run 31."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope


async def main() -> None:
    await init_engine(database_path())
    async with session_scope() as session:
        queries = [
            "SELECT id, job_type, state, lease_until, available_at, cancel_requested_at, payload_json FROM jobs WHERE id=169",
            "SELECT id, run_type, state, phase, counters_json, last_error_code FROM discovery_runs WHERE id=31",
            "SELECT id, job_type, state FROM jobs WHERE job_type='discovery' ORDER BY id DESC LIMIT 5",
        ]
        for q in queries:
            print("---")
            for row in await session.execute(text(q)):
                print(tuple(row))


if __name__ == "__main__":
    asyncio.run(main())
