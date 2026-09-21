"""Collect public Telegram sources from fresh order-phrase search hits, with no qualification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    PublicPostSearchRequest,
)
from telegram_lead_discovery.infrastructure.windows_proxy import (
    resolve_telegram_connection,
)


QUERIES = (
    "нужен разработчик",
    "ищу разработчика",
    "ищем разработчика",
    "нужен программист",
    "ищу программиста",
    "нужен сайт",
    "нужно сделать сайт",
    "нужен лендинг",
    "ищу разработчика сайта",
    "ищем разработчика сайта",
    "нужен телеграм бот",
    "нужен бот",
    "ищу разработчика бота",
    "нужен чат бот",
    "нужна интеграция",
    "нужен API",
    "нужна автоматизация",
    "нужен парсер",
    "разработать парсер",
    "посоветуйте разработчика",
    "порекомендуйте разработчика",
    "нужен интернет магазин",
    "нужен исполнитель",
    "ищу исполнителя",
)
FRESH_AFTER = datetime.now(UTC) - timedelta(days=7)
TARGET_SOURCES = 20


async def main() -> int:
    gateway = TelethonTelegramGateway(
        connection_config=resolve_telegram_connection("auto")
    )
    usernames: set[str] = set()
    await gateway.connect()
    try:
        for query in QUERIES:
            try:
                page = await gateway.search_public_posts(
                    PublicPostSearchRequest(schema_version=1, query=query, limit=100)
                )
            except GatewayFloodWait as exc:
                print(f"FLOOD_WAIT until={exc.until.isoformat()}", flush=True)
                break
            except (GatewayPremiumRequired, GatewaySearchQuotaExhausted) as exc:
                print(f"PUBLIC_SEARCH_UNAVAILABLE reason={exc}", flush=True)
                break
            for hit in page.hits:
                if hit.published_at.astimezone(UTC) >= FRESH_AFTER:
                    usernames.add(hit.source.username)
            if len(usernames) >= TARGET_SOURCES:
                break
            await asyncio.sleep(1)
    finally:
        await gateway.disconnect()
    for username in sorted(usernames):
        print(f"@{username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
