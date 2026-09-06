"""Quick Telethon connectivity probe."""

from __future__ import annotations

import asyncio

from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway


async def main() -> int:
    gw = TelethonTelegramGateway()
    try:
        snap = await asyncio.wait_for(gw.connect(), timeout=90)
        print(
            f"OK connected={snap.connected} account_id={snap.account_id} "
            f"user={snap.username!r}"
        )
        await gw.disconnect()
        return 0 if snap.connected else 2
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
