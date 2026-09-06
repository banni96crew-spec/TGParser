"""Cancel active discovery so a verification graph run can start."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope


async def main() -> None:
    await init_engine(database_path())
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, run_type, state FROM discovery_runs "
                    "WHERE state IN ('queued','running','cancelling',"
                    "'retry_wait_flood')"
                )
            )
        ).fetchall()
        print(f"active_before={rows}", flush=True)
        if rows:
            await session.execute(
                text(
                    "UPDATE discovery_runs SET state='cancelled', "
                    "finished_at=CURRENT_TIMESTAMP, "
                    "last_error_code='owner_restart_verify' "
                    "WHERE state IN ('queued','running','cancelling',"
                    "'retry_wait_flood')"
                )
            )
            await session.execute(
                text(
                    "UPDATE jobs SET state='cancelled', lease_until=NULL, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE job_type='discovery' AND state IN "
                    "('queued','running','retry_wait','leased')"
                )
            )
            await session.commit()
        rows2 = (
            await session.execute(
                text(
                    "SELECT id, run_type, state FROM discovery_runs "
                    "WHERE state IN ('queued','running','cancelling',"
                    "'retry_wait_flood')"
                )
            )
        ).fetchall()
        print(f"active_after={rows2}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
