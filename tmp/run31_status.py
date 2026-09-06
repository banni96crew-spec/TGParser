"""Detailed run 31 status."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope


async def main() -> None:
    await init_engine(database_path())
    async with session_scope() as session:
        run = (
            await session.execute(
                text(
                    "SELECT state, phase, counters_json, last_error_code, cursor_json, "
                    "started_at, finished_at FROM discovery_runs WHERE id=31"
                )
            )
        ).one()
        job = (
            await session.execute(
                text(
                    "SELECT state, lease_until, last_error_code FROM jobs WHERE id=169"
                )
            )
        ).one()
        print("run", run)
        print("job", job)
        cursor = json.loads(run[3] or "{}") if run[3] else json.loads(run[4] or "{}")
        if run[4]:
            cursor = json.loads(run[4])
        print("cursor keys", list(cursor.keys()) if cursor else None)
        print("current_node", cursor.get("current_node"))
        print("queue len", len(cursor.get("queue") or []))
        print("completed_stages keys", list((cursor.get("completed_stages") or {}).keys())[:5])
        print("counters", run[2])
        events = await session.execute(
            text(
                "SELECT COUNT(*) FROM source_discovery_events WHERE run_id=31"
            )
        )
        print("events", events.scalar_one())
        posts = await session.execute(
            text("SELECT COUNT(*) FROM graph_discovery_posts WHERE run_id=31")
        )
        print("graph_posts", posts.scalar_one())


if __name__ == "__main__":
    asyncio.run(main())
