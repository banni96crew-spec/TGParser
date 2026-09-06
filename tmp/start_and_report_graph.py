"""Start graph-only adjacent discovery and write results when terminal."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text

from telegram_lead_discovery.infrastructure.paths import database_path, lock_path
from telegram_lead_discovery.infrastructure.process_lock import is_runtime_running
from telegram_lead_discovery.source_discovery.graph_discovery import start_graph_discovery_run
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.db import init_engine, session_scope
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    Job,
    SourceDiscoveryEvent,
    TelegramSource,
)

SEED_REFS = [
    "@workk_onchat",
    "@designer_jobs",
    "@GetClient",
    "@program_job",
    "@poiskfreelance",
    "@mari_vakansii",
    "@freelance_chatik0",
    "@freelancerscha",
    "@rueventjob4at",
]

OUT_PATH = Path(__file__).resolve().parent / "graph_run_result.txt"


async def _resolve_seed_ids(session) -> tuple[list[int], list[tuple[str, str]]]:
    seed_ids: list[int] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in SEED_REFS:
        key = raw.strip().lower()
        if key in seen:
            skipped.append((raw, "duplicate"))
            continue
        seen.add(key)
        try:
            username = normalize_username(raw)
        except InvalidUsernameError:
            skipped.append((raw, "invalid_username"))
            continue
        row = (
            await session.execute(
                select(TelegramSource).where(
                    TelegramSource.username_normalized == username
                )
            )
        ).scalar_one_or_none()
        if row is None:
            skipped.append((raw, "not_in_db"))
            continue
        if row.telegram_id is None:
            skipped.append((raw, "unresolved"))
            continue
        seed_ids.append(row.id)
        print(
            f"seed OK {raw} -> id={row.id} tg={row.telegram_id}",
            flush=True,
        )
    return seed_ids, skipped


async def _poll(run_id: int, *, timeout_seconds: float = 7200.0) -> DiscoveryRun:
    deadline = time.monotonic() + timeout_seconds
    last: tuple[str, str, str] | None = None
    while time.monotonic() < deadline:
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None:
                raise RuntimeError(f"run_not_found:{run_id}")
            key = (run.state, run.phase or "", run.counters_json or "")
            if key != last:
                print(
                    f"[{datetime.now(UTC).isoformat()}] run={run_id} "
                    f"state={run.state} phase={run.phase} "
                    f"counters={run.counters_json} error={run.last_error_code!r}",
                    flush=True,
                )
                last = key
            if run.state in {"succeeded", "partial", "failed", "cancelled"}:
                return run
        await asyncio.sleep(10)
    raise TimeoutError(f"run_poll_timeout:{run_id}")


async def _write_report(run_id: int, skipped: list[tuple[str, str]]) -> Path:
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        assert run is not None
        job = (
            await session.execute(
                select(Job).where(Job.dedupe_key == f"graph-discovery:{run_id}")
            )
        ).scalar_one_or_none()
        events = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvent)
                    .where(SourceDiscoveryEvent.run_id == run_id)
                    .order_by(SourceDiscoveryEvent.id.asc())
                )
            ).scalars()
        )
        posts = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM graph_discovery_posts WHERE run_id=:rid"
                ),
                {"rid": run_id},
            )
        ).scalar_one()
        source_ids = [
            e.source_id
            for e in events
            if e.source_id is not None and e.outcome in {"candidate", "merged"}
        ]
        candidates = []
        if source_ids:
            candidates = list(
                (
                    await session.execute(
                        select(TelegramSource)
                        .where(TelegramSource.id.in_(source_ids))
                        .order_by(TelegramSource.id.asc())
                    )
                ).scalars()
            )

        root_ids = json.loads(run.root_source_ids_json or "[]")
        roots = []
        for sid in root_ids:
            row = await session.get(TelegramSource, int(sid))
            if row is not None:
                roots.append(
                    f"@{row.username_normalized} id={row.id} tg={row.telegram_id}"
                )

        cursor = json.loads(run.cursor_json or "{}")
        counters = json.loads(run.counters_json or "{}")
        lines = [
            "GRAPH ADJACENT DISCOVERY RESULT",
            f"generated_at_utc={datetime.now(UTC).isoformat()}",
            f"run_id={run.id}",
            f"run_type={run.run_type}",
            f"state={run.state}",
            f"phase={run.phase}",
            f"started_at={run.started_at}",
            f"finished_at={run.finished_at}",
            f"last_error_code={run.last_error_code!r}",
            f"termination={cursor.get('termination')}",
            f"job_id={job.id if job else None}",
            f"job_state={job.state if job else None}",
            f"job_attempt={job.attempt if job else None}",
            f"seed_refs={SEED_REFS}",
            f"seed_source_ids={root_ids}",
            f"seeds_resolved={roots}",
            f"seeds_skipped={skipped}",
            f"counters={json.dumps(counters, ensure_ascii=False)}",
            f"request_control={json.dumps(cursor.get('request_control'), ensure_ascii=False)}",
            f"events_total={len(events)}",
            f"graph_posts_total={posts}",
            f"candidates_found={len(candidates)}",
            "",
            "=== COMPLETED STAGES ===",
            json.dumps(cursor.get("completed_stages") or {}, ensure_ascii=False, indent=2),
            "",
            "=== EVENTS ===",
        ]
        for e in events:
            lines.append(
                f"id={e.id} method={e.method} outcome={e.outcome} "
                f"raw={e.raw_reference!r} norm={e.normalized_reference!r} "
                f"source_id={e.source_id} depth={e.depth}"
            )
        lines.append("")
        lines.append("=== CANDIDATE / MERGED SOURCES ===")
        if not candidates:
            lines.append("(none)")
        for s in candidates:
            lines.append(
                f"id={s.id} @{s.username_normalized} tg={s.telegram_id} "
                f"title={s.title!r} state={s.lifecycle_state}"
            )
        lines.append("")
        lines.append("NOTE: run_type=graph only; keyword/global search was NOT started.")

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUT_PATH


async def main() -> int:
    print(f"runtime_lock={lock_path().exists()} alive={is_runtime_running()}", flush=True)
    if not is_runtime_running():
        print("FAIL: tld runtime not running — start tld first", flush=True)
        return 2

    await init_engine(database_path())
    async with session_scope() as session:
        active = await session.execute(
            text(
                "SELECT id, run_type, state FROM discovery_runs "
                "WHERE state IN ('queued','running','cancelling','retry_wait_flood')"
            )
        )
        active_rows = active.fetchall()
        if active_rows:
            print(f"FAIL: active discovery blocks start: {active_rows}", flush=True)
            return 3

        seed_ids, skipped = await _resolve_seed_ids(session)
        if not seed_ids:
            print(f"FAIL: no seeds resolved; skipped={skipped}", flush=True)
            return 4

        started = await start_graph_discovery_run(session, seed_source_ids=seed_ids)
        run_id = started.run.id
        print(
            f"started graph run_id={run_id} job_id={started.job.id} "
            f"seeds={seed_ids} skipped={skipped}",
            flush=True,
        )

    final = await _poll(run_id)
    path = await _write_report(run_id, skipped)
    print(
        f"DONE state={final.state} error={final.last_error_code!r} report={path}",
        flush=True,
    )
    print(path.read_text(encoding="utf-8"), flush=True)
    return 0 if final.state in {"succeeded", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
