"""Check linked public discussion groups of discovered job channels."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from find_one_qualified_chat import _check_megagroup
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    PublicSourceRef,
    SourceRef,
)
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection

CHANNELS = (
    "Koteyka_Freelancer", "freelancetaverna", "proffreelancee_chat",
    "THE_POMOGATOR", "astya_r", "copywritingru", "webstepsru",
)
OUTPUT = Path(__file__).resolve().parent / "linked_discussion_candidates.txt"
LEDGER = Path(__file__).resolve().parent / "linked_discussion_ledger.txt"


def _write(rows: list[dict[str, object]], now: datetime) -> None:
    lines = [
        "СВЯЗАННЫЕ ПУБЛИЧНЫЕ ОБСУЖДЕНИЯ НАЙДЕННЫХ КАНАЛОВ",
        f"Проверка UTC: {now.isoformat()}",
        f"Найдено: {len(rows)}",
        "",
    ]
    for row in rows:
        lines.append(f"@{row['username']} | {row['status']} | {row['reason']}")
        for link in row.get("evidence", []):
            lines.append(f"  {link}")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    previous = set(LEDGER.read_text(encoding="utf-8").splitlines()) if LEDGER.exists() else set()
    additions = [line for line in lines if line.startswith("@") and line not in previous]
    if additions:
        with LEDGER.open("a", encoding="utf-8") as ledger:
            ledger.write("\n".join(additions) + "\n")


async def main() -> int:
    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    await gateway.connect()
    try:
        for index, username in enumerate(CHANNELS, 1):
            try:
                parent = await gateway.resolve_public_source(
                    PublicSourceRef(schema_version=1, username_or_url=username)
                )
                linked = await gateway.get_linked_discussion(SourceRef(
                    schema_version=1,
                    source_id=index,
                    telegram_id=parent.telegram_id,
                    username=parent.username,
                    access_hash=parent.access_hash,
                ))
                if linked is None:
                    continue
                result = await _check_megagroup(gateway, linked, 1000 + index, now)
                row = {"username": linked.username, **result}
                rows.append(row)
                if row["status"] == "qualified":
                    _write(rows, now)
                    print(f"@{linked.username}")
                    return 0
            except GatewayFloodWait as exc:
                _write(rows, now)
                print(f"FLOOD_WAIT until={exc.until.isoformat()}")
                return 2
    finally:
        await gateway.disconnect()
    _write(rows, now)
    print("NO_QUALIFIED_SOURCE")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
