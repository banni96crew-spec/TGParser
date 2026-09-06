"""One-off live graph discovery run — adjacent channels only (no keyword search)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import select, text

from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import PublicSourceRef
from telegram_lead_discovery.infrastructure.paths import database_path, lock_path
from telegram_lead_discovery.source_discovery.graph_discovery import start_graph_discovery_run
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.source_discovery.source_candidates import add_manual_candidate
from telegram_lead_discovery.storage.db import init_engine, session_scope
from telegram_lead_discovery.storage.models import DiscoveryRun, TelegramSource

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


async def _ensure_seed(
    session,
    gateway: TelethonTelegramGateway,
    raw: str,
) -> tuple[int | None, str | None]:
    """Return (source_id, error_code)."""
    try:
        username = normalize_username(raw)
    except InvalidUsernameError:
        username = None

    if username is not None:
        existing = await session.execute(
            select(TelegramSource).where(TelegramSource.username_normalized == username)
        )
        row = existing.scalar_one_or_none()
        if row is not None and row.telegram_id is not None:
            return row.id, None
        source, _ = await add_manual_candidate(
            session,
            username_or_url=raw,
            gateway=gateway,
            method="seed_import",
        )
        if source.telegram_id is None:
            return None, "unresolved"
        return source.id, None

    # Invite / non-username ref: resolve via Telethon get_entity on raw URL.
    await session.commit()
    snap = await gateway.resolve_public_source(
        PublicSourceRef(schema_version=1, username_or_url=raw.strip())
    )
    username_norm = (snap.username or "").lower() or None
    if username_norm:
        existing = await session.execute(
            select(TelegramSource).where(
                TelegramSource.username_normalized == username_norm
            )
        )
        row = existing.scalar_one_or_none()
    else:
        row = None
        existing = await session.execute(
            select(TelegramSource).where(TelegramSource.telegram_id == snap.telegram_id)
        )
        row = existing.scalar_one_or_none()
    if row is None:
        row = TelegramSource(
            telegram_id=snap.telegram_id,
            access_hash=snap.access_hash,
            username_normalized=username_norm or f"peer_{snap.telegram_id}",
            title=snap.title,
            source_type=snap.source_type,
            public_url=snap.public_url,
            lifecycle_state="candidate",
            quality_score=2,
        )
        session.add(row)
        await session.flush()
    else:
        if row.telegram_id is None:
            row.telegram_id = snap.telegram_id
        if row.access_hash is None and snap.access_hash is not None:
            row.access_hash = snap.access_hash
        await session.flush()
    if row.telegram_id is None:
        return None, "unresolved"
    return row.id, None


async def _poll_run(run_id: int, *, timeout_seconds: float = 3600.0) -> DiscoveryRun:
    deadline = time.monotonic() + timeout_seconds
    last_state: tuple[str, str] | None = None
    while time.monotonic() < deadline:
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None:
                raise RuntimeError(f"run_not_found:{run_id}")
            key = (run.state, run.phase or "")
            if key != last_state:
                counters = json.loads(run.counters_json or "{}")
                print(
                    f"[{datetime.now(UTC).isoformat()}] run={run_id} "
                    f"state={run.state} phase={run.phase} counters={counters} "
                    f"error={run.last_error_code!r}",
                    flush=True,
                )
                last_state = key
            if run.state in {"succeeded", "partial", "failed", "cancelled"}:
                return run
        await asyncio.sleep(5)
    raise TimeoutError(f"run_poll_timeout:{run_id}")


async def main() -> int:
    if lock_path().exists():
        print("runtime lock present — assuming tld is running", flush=True)
    else:
        print(
            "WARNING: no runtime lock — start `tld start` in another terminal first",
            flush=True,
        )

    await init_engine(database_path())
    gateway = TelethonTelegramGateway()
    account = await gateway.connect()
    print(
        f"telegram connected={account.connected} account_id={account.account_id} "
        f"username={account.username!r}",
        flush=True,
    )
    if not account.connected:
        print("FAIL: telegram not connected", flush=True)
        return 1

    seen: set[str] = set()
    seed_ids: list[int] = []
    skipped: list[tuple[str, str]] = []

    async with session_scope() as session:
        active = await session.execute(
            text(
                "SELECT id, run_type, state FROM discovery_runs "
                "WHERE state IN ('queued','running','cancelling','retry_wait_flood')"
            )
        )
        active_rows = active.fetchall()
        if active_rows:
            print(f"FAIL: active discovery run blocks start: {active_rows}", flush=True)
            return 2

        for raw in SEED_REFS:
            key = raw.strip().lower()
            if key in seen:
                print(f"skip duplicate ref: {raw}", flush=True)
                continue
            seen.add(key)
            try:
                source_id, err = await _ensure_seed(session, gateway, raw)
            except Exception as exc:  # noqa: BLE001
                skipped.append((raw, type(exc).__name__))
                print(f"seed FAIL {raw}: {type(exc).__name__}: {exc}", flush=True)
                continue
            if source_id is None:
                skipped.append((raw, err or "unknown"))
                print(f"seed SKIP {raw}: {err}", flush=True)
                continue
            seed_ids.append(source_id)
            print(f"seed OK {raw} -> source_id={source_id}", flush=True)

        if not seed_ids:
            print("FAIL: no resolved seeds", flush=True)
            return 3

        started = await start_graph_discovery_run(session, seed_source_ids=seed_ids)
        run_id = started.run.id
        job_id = started.job.id
        await session.commit()
        print(
            f"started graph run_id={run_id} job_id={job_id} seeds={len(seed_ids)} "
            f"seed_source_ids={seed_ids}",
            flush=True,
        )

    final = await _poll_run(run_id)
    counters = json.loads(final.counters_json or "{}")
    print(
        f"DONE run_id={run_id} state={final.state} phase={final.phase} "
        f"error={final.last_error_code!r} counters={json.dumps(counters, ensure_ascii=False)}",
        flush=True,
    )
    if skipped:
        print(f"skipped seeds: {skipped}", flush=True)
    await gateway.disconnect()
    return 0 if final.state in {"succeeded", "partial"} else 4


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
