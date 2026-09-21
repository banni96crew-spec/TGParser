"""Discover public Telegram sources and stop only after a fully qualified chat is found."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    DirectorySearchRequest,
    GatewayFloodWait,
    HistoryRequest,
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

QUERIES = (
    "заказ сайта", "ищу программиста", "ищу разработчика", "ищу бота",
    "заказ бот", "нужен сайт", "заказ парсера", "интеграция API",
    "автоматизация бизнес", "разработка телеграм", "заказ лендинга",
    "нужен разработчик", "ищу интегратора", "веб разработка заказ",
)
DIRECT_CATEGORIES = {"direct_order", "contractor_search", "recommendation_request"}
SOURCE_CAP = 1500
PAGE_SIZE = 100
OUTPUT = Path(__file__).resolve().parent / "all_discovered_chats.txt"
RULE_CHECKSUM = catalog_checksum(ACTIVE_SEED_RULES)


def _client_request(text: str, category: str) -> bool:
    normalized = " ".join(text.lower().split())
    client_markers = (
        "ищу разработчика", "ищем разработчика", "ищу программиста",
        "ищем программиста", "нужен разработчик", "нужна разработка",
        "нужен сайт", "нужна сайт", "нужен лендинг", "нужен бот",
        "нужен телеграм бот", "нужен парсер", "нужна автоматизация",
        "нужна интеграция", "нужен api", "посоветуйте разработчика",
        "порекомендуйте разработчика", "ищу исполнителя", "нужен исполнитель",
        "нужно сделать", "нужно разработать", "нужно настроить",
        "требуется разработчик", "требуется сделать",
    )
    executor_markers = (
        "ищу заказы", "ищу заказ", "возьму заказ", "беру заказы", "мои услуги",
        "моё портфолио", "мое портфолио", "я разработчик", "я программист",
        "я веб-дизайнер", "разрабатываю сайты", "создаю сайты", "настраиваю ботов",
        "предлагаю услуги", "#помогу", "#резюме", "что делаю", "основной стек",
        "стоимость зависит от конкретной задачи", "разберусь в задаче",
        "отдаём проект", "отдаем проект", "дешевле рынка", "сроки и цена письменно",
    )
    return (
        category in DIRECT_CATEGORIES
        and any(marker in normalized for marker in client_markers)
        and not any(marker in normalized for marker in executor_markers)
    )


async def _check_megagroup(
    gateway: TelethonTelegramGateway, source: object, source_id: int, now: datetime
) -> dict[str, object]:
    username = str(getattr(source, "username"))
    telegram_id = int(getattr(source, "telegram_id"))
    access_hash = getattr(source, "access_hash")
    if access_hash is None:
        return {"status": "not_qualified", "reason": "no_access_hash"}
    accumulator = ActiveChatAccumulator(reference_at=now)
    evidence: list[str] = []
    evidence_authors: set[str] = set()
    offset_id = 0
    scanned = 0
    while scanned < SOURCE_CAP:
        request = HistoryRequest(
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
        )
        page = [message async for message in gateway.iter_history(request)]
        if not page:
            break
        reached_window = False
        for message in page:
            published = message.published_at.astimezone(UTC)
            if published < now - timedelta(days=30):
                reached_window = True
                break
            scanned += 1
            offset_id = int(message.telegram_message_id)
            _, normalized_hash, detection = qualify_excerpt_text(
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
            is_client = _client_request(message.text or "", detection.category)
            countable = accumulator.consume(ActiveChatMessage(
                telegram_message_id=int(message.telegram_message_id),
                published_at=published,
                normalized_hash=normalized_hash,
                author_kind=author_kind,
                author_key=author_key,
                detection_category=detection.category if is_client else "irrelevant",
                service_profiles=tuple(detection.service_profiles) if is_client else (),
                hard_exclusion=detection.hard_exclusion,
            ))
            if countable and author_key and author_key not in evidence_authors:
                evidence_authors.add(author_key)
                if message.permalink:
                    evidence.append(message.permalink)
        if reached_window or len(page) < request.limit:
            break
        await asyncio.sleep(1)
    counters = accumulator.counters()
    thresholds = active_chat_thresholds(counters, reference_at=now)
    missing = [name for name, passed in thresholds.items() if not passed]
    return {
        "status": "qualified" if not missing else "not_qualified",
        "reason": "all_thresholds" if not missing else ",".join(missing),
        "scanned": scanned,
        "counters": asdict(counters),
        "evidence": evidence[:3],
    }


def _write_report(rows: list[dict[str, object]], now: datetime) -> None:
    previous = []
    if OUTPUT.exists():
        previous = [
            line for line in OUTPUT.read_text(encoding="utf-8").splitlines()
            if line.startswith("@")
        ]
    lines = [
        "НАЙДЕННЫЕ TELEGRAM-ИСТОЧНИКИ",
        f"Проверка UTC: {now.isoformat()}",
        "Поиск: публичный каталог Telegram; новых источников после первого полного совпадения не искали.",
        f"Всего найдено в этом проходе: {len(rows)}",
        "",
    ]
    lines.extend(previous)
    for row in rows:
        lines.append(
            f"@{row['username']} | {row['source_type']} | {row['status']} | {row['reason']}"
        )
        for link in row.get("evidence", []):
            lines.append(f"  {link}")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    now = datetime.now(UTC)
    found: dict[int, dict[str, object]] = {}
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    await gateway.connect()
    try:
        for query in QUERIES:
            try:
                candidates = await gateway.search_public_sources(
                    DirectorySearchRequest(schema_version=1, query=query, limit=50)
                )
                for source in candidates:
                    found.setdefault(
                        source.telegram_id,
                        {
                            "username": source.username,
                            "title": source.title,
                            "source_type": source.source_type,
                            "status": "found",
                            "reason": f"query:{query}",
                            "source": source,
                        },
                    )
                qualified_username: str | None = None
                for source_id, row in enumerate(list(found.values()), 1):
                    if row["status"] != "found":
                        continue
                    if row["source_type"] != "megagroup":
                        row.update(status="not_qualified", reason="not_megagroup")
                        continue
                    result = await _check_megagroup(gateway, row["source"], source_id, now)
                    row.update(result)
                    if row["status"] == "qualified":
                        qualified_username = str(row["username"])
                if qualified_username is not None:
                    clean_rows = [{key: value for key, value in item.items() if key != "source"} for item in found.values()]
                    _write_report(clean_rows, now)
                    print(f"@{qualified_username}", flush=True)
                    return 0
                await asyncio.sleep(1)
            except GatewayFloodWait as exc:
                clean_rows = [{key: value for key, value in item.items() if key != "source"} for item in found.values()]
                _write_report(clean_rows, now)
                print(f"FLOOD_WAIT until={exc.until.isoformat()}", flush=True)
                return 2
    finally:
        await gateway.disconnect()
    clean_rows = [{key: value for key, value in item.items() if key != "source"} for item in found.values()]
    _write_report(clean_rows, now)
    print("NO_QUALIFIED_SOURCE", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
