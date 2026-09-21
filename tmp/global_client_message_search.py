"""Global-message discovery of public client-order supergroups only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from find_one_qualified_chat import _check_megagroup, _client_request
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GlobalSearchRequest,
    HistoryRequest,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


KEYWORDS = (
    "нужен разработчик", "ищу разработчика", "ищем разработчика",
    "нужен программист", "ищу программиста", "ищем программиста",
    "нужен веб разработчик", "ищу веб разработчика", "нужен исполнитель",
    "ищу исполнителя", "нужен сайт", "нужно сделать сайт", "нужен лендинг",
    "нужно сделать лендинг", "нужен телеграм бот", "нужен Telegram бот",
    "ищу разработчика бота", "нужен чат бот", "нужна интеграция",
    "нужна интеграция API", "нужна автоматизация", "нужен парсер",
    "нужно разработать парсер", "порекомендуйте разработчика",
    "посоветуйте разработчика", "порекомендуйте программиста",
    "посоветуйте программиста", "нужен специалист по автоматизации",
    "нужен разработчик интернет магазина",
)
OUTPUT = Path(__file__).resolve().parent / "global_client_message_search.txt"
SEARCH_LIMIT = 100
HISTORY_CAP = 1500
PAGE_SIZE = 100
RULE_CHECKSUM = catalog_checksum(ACTIVE_SEED_RULES)


def _header(now: datetime) -> list[str]:
    return [
        "ГЛОБАЛЬНЫЙ ПОИСК КЛИЕНТСКИХ СООБЩЕНИЙ TELEGRAM",
        f"Запуск UTC: {now.isoformat()}",
        "",
        "КЛЮЧЕВЫЕ ФРАЗЫ:",
        *[f"- {keyword}" for keyword in KEYWORDS],
        "",
        "РЕЗУЛЬТАТЫ:",
    ]


async def _three_manual_candidates(
    gateway: TelethonTelegramGateway, source: object, source_id: int, now: datetime
) -> list[tuple[str, str, str]]:
    username = str(getattr(source, "username"))
    telegram_id = int(getattr(source, "telegram_id"))
    access_hash = getattr(source, "access_hash")
    if access_hash is None:
        return []
    orders: list[tuple[str, str, str]] = []
    authors: set[int] = set()
    offset_id = 0
    scanned = 0
    while scanned < HISTORY_CAP:
        request = HistoryRequest(
            schema_version=1,
            source_id=source_id,
            peer=TelegramPeerRef(
                schema_version=1,
                telegram_peer_id=telegram_id,
                access_hash=int(access_hash),
                username_normalized=username,
            ),
            limit=min(PAGE_SIZE, HISTORY_CAP - scanned),
            purpose="global_client_message_verification",
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
            if message.author_kind != "user" or message.author_peer_id is None:
                continue
            detection = detect(
                message.text or "", rules=ACTIVE_SEED_RULES, rule_set_checksum=RULE_CHECKSUM
            )
            if not _client_request(message.text or "", detection.category):
                continue
            if message.author_peer_id in authors or not message.permalink:
                continue
            authors.add(message.author_peer_id)
            text = " ".join((message.text or "").split())[:600]
            orders.append((published.date().isoformat(), message.permalink, text))
            if len(orders) == 3:
                return orders
        if reached_window or len(page) < request.limit:
            break
        await asyncio.sleep(1)
    return orders


async def main() -> int:
    now = datetime.now(UTC)
    lines = _header(now)
    candidates: dict[int, object] = {}
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        await gateway.connect()
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ОСТАНОВЛЕНО: ошибка соединения Telegram: {type(exc).__name__}: {exc}")
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"CONNECT_ERROR={type(exc).__name__}", flush=True)
        return 3
    try:
        for keyword in KEYWORDS:
            try:
                page = await gateway.search_global(
                    GlobalSearchRequest(
                        schema_version=1, query=keyword, groups_only=True, limit=SEARCH_LIMIT
                    )
                )
            except GatewayFloodWait as exc:
                lines.append(f"ОСТАНОВЛЕНО: ограничение Telegram до {exc.until.isoformat()}")
                OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print("FLOOD_WAIT", flush=True)
                return 2
            for hit in page.hits:
                source = hit.source
                if source.source_type != "megagroup" or not source.username:
                    continue
                candidates.setdefault(int(source.telegram_id), source)
            await asyncio.sleep(1)

        lines.append(f"Найдено публичных супергрупп из сообщений: {len(candidates)}")
        for source_id, source in enumerate(candidates.values(), 1):
            try:
                orders = await _three_manual_candidates(gateway, source, source_id, now)
            except GatewayFloodWait as exc:
                lines.append(f"ОСТАНОВЛЕНО: ограничение Telegram до {exc.until.isoformat()}")
                OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print("FLOOD_WAIT", flush=True)
                return 2
            username = str(getattr(source, "username"))
            if len(orders) < 3:
                lines.append(f"@{username} | отклонён до проверки активности | заказов от разных авторов: {len(orders)}")
                continue
            lines.append(f"@{username} | три заказа подтверждены до проверки активности")
            for published, permalink, text in orders:
                lines.append(f"  {published} {permalink}")
                lines.append(f"  {text}")
            try:
                result = await _check_megagroup(gateway, source, source_id, now)
            except GatewayFloodWait as exc:
                lines.append(f"ОСТАНОВЛЕНО: ограничение Telegram до {exc.until.isoformat()}")
                OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print("FLOOD_WAIT", flush=True)
                return 2
            lines.append(f"@{username} | {result['status']} | {result['reason']}")
            if result["status"] == "qualified":
                OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
                print(f"QUALIFIED=@{username}", flush=True)
                return 0
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ОСТАНОВЛЕНО: ошибка Telegram: {type(exc).__name__}: {exc}")
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"TELEGRAM_ERROR={type(exc).__name__}", flush=True)
        return 3
    finally:
        await gateway.disconnect()
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("NO_QUALIFIED_SOURCE", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
