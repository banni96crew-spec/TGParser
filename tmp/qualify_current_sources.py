"""Strictly qualify only the user-supplied public Telegram sources."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    HistoryRequest,
    PublicSourceRef,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.infrastructure.windows_proxy import (
    resolve_telegram_connection,
)
from telegram_lead_discovery.source_discovery.active_chat import (
    ActiveChatAccumulator,
    ActiveChatMessage,
    active_chat_thresholds,
    source_scoped_author_key,
)
from telegram_lead_discovery.source_discovery.evidence import qualify_excerpt_text

USERNAMES = (
    "job_for_bots", "finddeveloper", "aivacancychannel", "tgram_jobs",
    "getclient", "golubin_channel", "webfrl", "startupfellows", "it_vac",
    "freelancce", "startup_job_russia", "devshr", "FreelancehuntProjects",
    "smmlancer", "StorkLife", "digitaltender", "rueventjob", "zerocode_jobs",
    "workayte", "ai_agent_submarine", "vibecode_ai", "gamedevpublisher",
)
SOURCE_CAP = 1500
PAGE_SIZE = 100
RULE_CHECKSUM = catalog_checksum(ACTIVE_SEED_RULES)
_CLIENT_INTENT = re.compile(
    r"(?:"
    r"\b(?:ищу|ищем)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)\b|"
    r"\b(?:нужен|нужна|нужны|требуется)\s+(?:разработчик|программист|специалист|исполнитель|подрядчик|команда|сайт|лендинг|бот|чат[- ]?бот|парсер|автоматизация|интеграция|интернет[- ]?магазин)\b|"
    r"\b(?:кто|кто-нибудь)\s+(?:может|сможет|готов)\s+(?:сделать|разработать|настроить|написать|создать|подключить|интегрировать)\b|"
    r"\b(?:нужно|необходимо|требуется)\s+(?:сделать|разработать|настроить|написать|создать|подключить|интегрировать)\b|"
    r"\b(?:посоветуйте|порекомендуйте)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)\b"
    r")", re.IGNORECASE,
)
_EXECUTOR_OFFER = re.compile(
    r"(?:"
    r"\b(?:я|мы)\s+(?:веб[- ]?дизайнер|разработчик|программист|технический специалист|фрилансер)\b|"
    r"\b(?:разрабатываю|создаю|делаю|настраиваю|предлагаю)\b|"
    r"\b(?:ищу|возьму)\s+(?:заказ|заказы|проект|проекты|клиента|клиентов)\b|"
    r"\b(?:мои услуги|портфолио|готов выполнить|готов взяться|беру заказы)\b|"
    r"#(?:помогу|вебдизайнер|разработчик|программист|техспец)\b"
    r")", re.IGNORECASE,
)


def _is_client_request(text: str, category: str) -> bool:
    return (
        category in {"direct_order", "contractor_search", "recommendation_request"}
        and bool(_CLIENT_INTENT.search(" ".join(text.split())))
        and not bool(_EXECUTOR_OFFER.search(" ".join(text.split())))
    )


async def _qualifies(
    gateway: TelethonTelegramGateway, snapshot: object, source_id: int, now: datetime
) -> bool:
    telegram_id = int(getattr(snapshot, "telegram_id"))
    username = str(getattr(snapshot, "username"))
    access_hash = getattr(snapshot, "access_hash")
    if access_hash is None:
        return False
    accumulator = ActiveChatAccumulator(reference_at=now)
    scanned = 0
    offset_id = 0
    while scanned < SOURCE_CAP:
        page = [message async for message in gateway.iter_history(HistoryRequest(
            schema_version=1,
            source_id=source_id,
            peer=TelegramPeerRef(
                schema_version=1,
                telegram_peer_id=telegram_id,
                access_hash=int(access_hash),
                username_normalized=username,
            ),
            limit=min(PAGE_SIZE, SOURCE_CAP - scanned),
            purpose="scouting_verification",
            continuation_cursor=str(offset_id) if offset_id else None,
        ))]
        if not page:
            break
        reached_30d = False
        for message in page:
            published = message.published_at.astimezone(UTC)
            if published < now - timedelta(days=30):
                reached_30d = True
                break
            scanned += 1
            offset_id = int(message.telegram_message_id)
            _, normalized_hash, detected = qualify_excerpt_text(
                message.text or "",
                detect_fn=lambda text: detect(
                    text, rules=ACTIVE_SEED_RULES, rule_set_checksum=RULE_CHECKSUM
                ),
            )
            author_kind = message.author_kind
            author_key = None
            if author_kind == "user" and message.author_peer_id is not None:
                author_key = source_scoped_author_key(telegram_id, message.author_peer_id)
            elif author_kind == "user":
                author_kind = "unknown"
            is_client = _is_client_request(message.text or "", detected.category)
            accumulator.consume(ActiveChatMessage(
                telegram_message_id=int(message.telegram_message_id),
                published_at=published,
                normalized_hash=normalized_hash,
                author_kind=author_kind,
                author_key=author_key,
                detection_category=detected.category if is_client else "irrelevant",
                service_profiles=tuple(detected.service_profiles) if is_client else (),
                hard_exclusion=detected.hard_exclusion,
            ))
        if reached_30d or len(page) < PAGE_SIZE:
            break
        await asyncio.sleep(1)
    return all(active_chat_thresholds(accumulator.counters(), reference_at=now).values())


async def main() -> int:
    now = datetime.now(UTC)
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    full: list[str] = []
    await gateway.connect()
    try:
        for source_id, username in enumerate(USERNAMES, 1):
            try:
                snapshot = await gateway.resolve_public_source(
                    PublicSourceRef(schema_version=1, username_or_url=username)
                )
                if snapshot.source_type != "megagroup":
                    continue
                if await _qualifies(gateway, snapshot, source_id, now):
                    full.append(snapshot.username)
            except GatewayFloodWait as exc:
                print(f"FLOOD_WAIT until={exc.until.isoformat()}", flush=True)
                return 2
    finally:
        await gateway.disconnect()
    for username in full:
        print(f"@{username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
