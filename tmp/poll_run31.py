"""Poll graph run 31 until terminal."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

from sqlalchemy import text

from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope


async def main() -> int:
    await init_engine(database_path())
    run_id = 31
    deadline = time.monotonic() + 7200
    last = None
    while time.monotonic() < deadline:
        async with session_scope() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT state, phase, counters_json, last_error_code, cursor_json "
                        "FROM discovery_runs WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            ).one()
            state, phase, counters_json, error, cursor_json = row
            key = (state, phase, counters_json)
            if key != last:
                counters = json.loads(counters_json or "{}")
                cursor = json.loads(cursor_json or "{}") if cursor_json else {}
                queue_len = len(cursor.get("queue") or [])
                current = (cursor.get("current_node") or {}).get("username")
                print(
                    f"[{datetime.now(UTC).isoformat()}] state={state} phase={phase} "
                    f"node={current!r} queue={queue_len} counters={counters} error={error!r}",
                    flush=True,
                )
                last = key
            if state in {"succeeded", "partial", "failed", "cancelled"}:
                print(f"DONE state={state}", flush=True)
                return 0 if state in {"succeeded", "partial"} else 1
        await asyncio.sleep(15)
    print("TIMEOUT", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
