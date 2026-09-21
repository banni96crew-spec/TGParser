"""Print three distinct-author client-order posts used for @workk_onchat qualification."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    HistoryRequest,
    PublicSourceRef,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection
from telegram_lead_discovery.source_discovery.active_chat import source_scoped_author_key
from telegram_lead_discovery.source_discovery.evidence import qualify_excerpt_text

RULE_CHECKSUM = catalog_checksum(ACTIVE_SEED_RULES)
_INTENT = re.compile(
    r"(?:ищу|ищем)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)|"
    r"(?:нужен|нужна|нужны|требуется)\s+(?:разработчик|программист|специалист|исполнитель|подрядчик|команда|сайт|лендинг|бот|чат[- ]?бот|парсер|автоматизация|интеграция|интернет[- ]?магазин)|"
    r"(?:нужно|необходимо|требуется)\s+(?:сделать|разработать|настроить|написать|создать|подключить|интегрировать)|"
    r"(?:посоветуйте|порекомендуйте)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"ищу заказы|ищу заказ|возьму заказ|беру заказы|мои услуги|портфолио|я разработчик|я программист|я веб-дизайнер|разрабатываю сайты|создаю сайты|настраиваю ботов|предлагаю услуги|#помогу|#резюме",
    re.IGNORECASE,
)


async def main() -> int:
    now = datetime.now(UTC)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    await gateway.connect()
    try:
        source = await gateway.resolve_public_source(
            PublicSourceRef(schema_version=1, username_or_url="workk_onchat")
        )
        if source.access_hash is None:
            return 1
        offset_id = 0
        scanned = 0
        authors: set[str] = set()
        while scanned < 1500 and len(authors) < 3:
            request = HistoryRequest(
                schema_version=1,
                source_id=1,
                peer=TelegramPeerRef(
                    schema_version=1,
                    telegram_peer_id=source.telegram_id,
                    access_hash=source.access_hash,
                    username_normalized=source.username,
                ),
                limit=min(100, 1500 - scanned),
                purpose="scouting_verification",
                continuation_cursor=str(offset_id) if offset_id else None,
            )
            page = [message async for message in gateway.iter_history(request)]
            if not page:
                break
            for message in page:
                published = message.published_at.astimezone(UTC)
                if published < now - timedelta(days=30):
                    return 0
                scanned += 1
                offset_id = int(message.telegram_message_id)
                if message.author_kind != "user" or message.author_peer_id is None:
                    continue
                _, _, detected = qualify_excerpt_text(
                    message.text or "",
                    detect_fn=lambda text: detect(
                        text, rules=ACTIVE_SEED_RULES, rule_set_checksum=RULE_CHECKSUM
                    ),
                )
                text = message.text or ""
                if (
                    detected.category not in {"direct_order", "contractor_search", "recommendation_request"}
                    or not _INTENT.search(text)
                    or _OFFER.search(text)
                ):
                    continue
                author = source_scoped_author_key(source.telegram_id, message.author_peer_id)
                if author in authors:
                    continue
                authors.add(author)
                summary = " ".join(text.split())[:1200]
                print(
                    f"{published.date().isoformat()} | {message.permalink} | "
                    f"{detected.category} | {summary}"
                )
            if len(page) < request.limit:
                break
            await asyncio.sleep(1)
    except GatewayFloodWait as exc:
        print(f"FLOOD_WAIT until={exc.until.isoformat()}")
        return 2
    finally:
        await gateway.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
