from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import HistoryRequest, PublicSourceRef, TelegramPeerRef
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


MARKERS = ("ищу", "нужен", "нужна", "нужно", "требуется", "посовет", "порекоменд")
OUTPUT = Path(__file__).resolve().parent / "vakansi_chat_manual_review.txt"


async def main() -> None:
    now = datetime.now(UTC)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    await gateway.connect()
    try:
        source = await gateway.resolve_public_source(PublicSourceRef(schema_version=1, username_or_url="Vakansi_chat"))
        peer = TelegramPeerRef(schema_version=1, telegram_peer_id=int(source.telegram_id), access_hash=int(source.access_hash), username_normalized=str(source.username))
        lines: list[str] = []
        offset = 0
        while True:
            page = [m async for m in gateway.iter_history(HistoryRequest(schema_version=1, source_id=1, peer=peer, limit=100, purpose="manual_order_review", continuation_cursor=str(offset) if offset else None))]
            if not page:
                break
            stop = False
            for m in page:
                if m.published_at.astimezone(UTC) < now - timedelta(days=30):
                    stop = True
                    break
                offset = int(m.telegram_message_id)
                text = " ".join((m.text or "").split())
                if m.author_kind == "user" and any(marker in text.lower() for marker in MARKERS):
                    lines.extend([f"{m.published_at.date().isoformat()} {m.permalink}", text[:1000], ""])
            if stop or len(page) < 100:
                break
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    finally:
        await gateway.disconnect()


asyncio.run(main())
