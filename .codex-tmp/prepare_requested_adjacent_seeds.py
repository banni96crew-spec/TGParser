"""Resolve only the operator-requested graph seeds; no keyword search."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.infrastructure.paths import database_path
from telegram_lead_discovery.storage.db import init_engine, session_scope
from tmp.live_graph_run import _ensure_seed


SEED_REFS = [
    "https://t.me/python_chatt",
    "https://t.me/+R_KxUQG5hYo5ZjAy",
    "https://t.me/freelancerscha",
    "https://t.me/frilans_na_legke",
    "https://t.me/digitaltender",
    "https://t.me/TRemoters",
    "https://t.me/n8n_community",
    "https://t.me/coding_ru",
    "https://t.me/js_ru",
    "https://t.me/nodejs_ru",
]


async def main() -> int:
    await init_engine(database_path())
    gateway = TelethonTelegramGateway()
    account = await gateway.connect()
    if not account.connected:
        print("FAIL: telegram_not_connected", flush=True)
        return 1

    resolved: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    try:
        async with session_scope() as session:
            for raw in SEED_REFS:
                try:
                    source_id, error = await _ensure_seed(session, gateway, raw)
                except Exception as exc:  # noqa: BLE001
                    skipped.append(
                        {"ref": raw, "error": f"{type(exc).__name__}:{exc}"}
                    )
                    continue
                if source_id is None:
                    skipped.append({"ref": raw, "error": error or "unresolved"})
                    continue
                resolved.append({"ref": raw, "source_id": source_id})
    finally:
        await gateway.disconnect()

    print(
        "RESULT="
        + json.dumps(
            {"resolved": resolved, "skipped": skipped},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if resolved else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
