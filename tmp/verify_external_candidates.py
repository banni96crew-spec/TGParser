"""Verify externally discovered public groups in the owner-required order."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from find_one_qualified_chat import _check_megagroup
from global_client_message_search import _three_manual_candidates
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import GatewayFloodWait, PublicSourceRef
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


HANDLES = (
    "django_jobs_board",
)
OUTPUT = Path(__file__).resolve().parent / "global_client_message_search.txt"


def write(lines: list[str]) -> None:
    with OUTPUT.open("a", encoding="utf-8") as report:
        report.write("\n".join(lines) + "\n")


async def main() -> int:
    now = datetime.now(UTC)
    write(["", f"ПРОВЕРКА ВНЕШНИХ КАНДИДАТОВ UTC: {now.isoformat()}"])
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        await gateway.connect()
    except Exception as exc:  # noqa: BLE001
        write([f"ОСТАНОВЛЕНО: ошибка соединения Telegram: {type(exc).__name__}: {exc}"])
        print("CONNECT_ERROR", flush=True)
        return 3
    try:
        for source_id, handle in enumerate(HANDLES, 1):
            try:
                source = await gateway.resolve_public_source(
                    PublicSourceRef(schema_version=1, username_or_url=handle)
                )
                if source.source_type != "megagroup" or not source.username:
                    write([f"@{handle} | отклонён | не публичная супергруппа"])
                    continue
                orders = await _three_manual_candidates(gateway, source, source_id, now)
                if len(orders) < 3:
                    write([f"@{source.username} | отклонён до проверки активности | заказов от разных авторов: {len(orders)}"])
                    continue
                result = await _check_megagroup(gateway, source, source_id, now)
                write([f"@{source.username} | {result['status']} | {result['reason']}"])
                if result["status"] == "qualified":
                    for published, permalink, text in orders:
                        write([f"  {published} {permalink}", f"  {text}"])
                    print(f"QUALIFIED=@{source.username}", flush=True)
                    return 0
            except GatewayFloodWait as exc:
                write([f"ОСТАНОВЛЕНО: ограничение Telegram до {exc.until.isoformat()}"])
                print("FLOOD_WAIT", flush=True)
                return 2
            except Exception as exc:  # noqa: BLE001
                write([f"@{handle} | ошибка проверки: {type(exc).__name__}: {exc}"])
    finally:
        await gateway.disconnect()
    print("NO_QUALIFIED_SOURCE", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
