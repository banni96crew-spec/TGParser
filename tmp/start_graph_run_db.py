"""Start graph discovery run using existing DB seeds (no second Telegram session)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

from sqlalchemy import text

from telegram_lead_discovery.infrastructure.paths import database_path, lock_path
from telegram_lead_discovery.source_discovery.graph_discovery import start_graph_discovery_run
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.db import init_engine, session_scope
from telegram_lead_discovery.storage.models import DiscoveryRun

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

# Resolved from DB inspect (2026-08-20); invite link not in DB.
SEED_SOURCE_IDS = [6, 63, 12, 44, 60, 64, 65, 66, 67]


async def _poll_run(run_id: int, *, timeout_seconds: float = 7200.0) -> DiscoveryRun:
    deadline = time.monotonic() + timeout_seconds
    last_key: tuple[str, str] | None = None
    while time.monotonic() < deadline:
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None:
                raise RuntimeError(f"run_not_found:{run_id}")
            key = (run.state, run.phase or "")
            if key != last_key:
                counters = json.loads(run.counters_json or "{}")
                print(
                    f"[{datetime.now(UTC).isoformat()}] run={run_id} "
                    f"state={run.state} phase={run.phase} counters={counters} "
                    f"error={run.last_error_code!r}",
                    flush=True,
                )
                last_key = key
            if run.state in {"succeeded", "partial", "failed", "cancelled"}:
                return run
        await asyncio.sleep(10)
    raise TimeoutError(f"run_poll_timeout:{run_id}")


async def main() -> int:
    print(f"runtime lock={lock_path().exists()}", flush=True)
    await init_engine(database_path())

    async with session_scope() as session:
        active = await session.execute(
            text(
                "SELECT id, run_type, state FROM discovery_runs "
                "WHERE state IN ('queued','running','cancelling','retry_wait_flood')"
            )
        )
        if active.fetchall():
            print("FAIL: active discovery run exists", flush=True)
            return 2

        for raw in SEED_REFS:
            try:
                normalize_username(raw)
                print(f"seed ref OK (username): {raw}", flush=True)
            except InvalidUsernameError:
                print(f"seed ref SKIP (invite/non-username, not in DB): {raw}", flush=True)

        started = await start_graph_discovery_run(
            session, seed_source_ids=SEED_SOURCE_IDS
        )
        run_id = started.run.id
        job_id = started.job.id
        print(
            f"started graph run_id={run_id} job_id={job_id} "
            f"seed_source_ids={SEED_SOURCE_IDS}",
            flush=True,
        )

    final = await _poll_run(run_id)
    counters = json.loads(final.counters_json or "{}")
    print(
        f"DONE run_id={run_id} state={final.state} error={final.last_error_code!r} "
        f"counters={json.dumps(counters, ensure_ascii=False)}",
        flush=True,
    )
    return 0 if final.state in {"succeeded", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
