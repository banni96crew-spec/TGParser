"""One-off strict global message search for public client-order megagroups."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

from find_one_qualified_chat import _check_megagroup
from global_client_message_search import KEYWORDS, _three_manual_candidates
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.collector.ports import GatewayFloodWait
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


OUTPUT = Path(__file__).resolve().parent / "direct_group_message_search.txt"
PAGE_SIZE = 100
EXTRA_KEYWORDS = (
    "требуется разработчик",
    "требуется программист",
    "ищу специалиста",
    "ищем специалиста",
    "нужен специалист",
    "кто может сделать",
    "кто сделает",
    "порекомендуйте исполнителя",
    "посоветуйте исполнителя",
    "нужно разработать",
    "нужно доработать",
    "нужно настроить",
    "разработать сайт",
    "сделать сайт",
    "доработать сайт",
    "разработать бота",
    "сделать телеграм бота",
    "создать телеграм бота",
    "настроить интеграцию",
    "интеграция с CRM",
    "автоматизировать процесс",
    "написать парсер",
    "сделать парсер",
    "доработать интернет магазин",
)
QUERIES = tuple(dict.fromkeys((*KEYWORDS, *EXTRA_KEYWORDS)))


def _peer_id(message: object) -> int | None:
    peer = getattr(message, "peer_id", None)
    for name in ("channel_id", "chat_id"):
        value = getattr(peer, name, None)
        if value is not None:
            return int(value)
    return None


def _save(lines: list[str]) -> None:
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    now = datetime.now(UTC)
    after = now - timedelta(days=30)
    lines = [
        "ПРЯМОЙ ГЛОБАЛЬНЫЙ ПОИСК СООБЩЕНИЙ TELEGRAM",
        f"Запуск UTC: {now.isoformat()}",
        f"Период: {after.isoformat()} — {now.isoformat()}",
        "Режим: messages.searchGlobal, groups_only=true, полная пагинация",
        "",
        "КЛЮЧЕВЫЕ ФРАЗЫ:",
        *[f"- {query}" for query in QUERIES],
        "",
        "НАЙДЕННЫЕ ПУБЛИЧНЫЕ СУПЕРГРУППЫ:",
    ]
    candidates: dict[int, object] = {}
    discovery_hits: dict[int, list[str]] = {}
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        await gateway.connect()
        for query in QUERIES:
            offset_rate = 0
            offset_peer: object = InputPeerEmpty()
            offset_id = 0
            seen_cursors: set[tuple[int, int, int]] = set()
            while True:
                result = await gateway._invoke(SearchGlobalRequest(
                    q=query,
                    filter=InputMessagesFilterEmpty(),
                    min_date=after,
                    max_date=now,
                    offset_rate=offset_rate,
                    offset_peer=offset_peer,
                    offset_id=offset_id,
                    limit=PAGE_SIZE,
                    broadcasts_only=None,
                    groups_only=True,
                    users_only=None,
                    folder_id=None,
                ))
                messages = list(getattr(result, "messages", None) or ())
                chats = {
                    int(chat.id): chat
                    for chat in (getattr(result, "chats", None) or ())
                    if getattr(chat, "id", None) is not None
                }
                if not messages:
                    break
                for message in messages:
                    chat_id = _peer_id(message)
                    chat = chats.get(chat_id or 0)
                    snapshot = _try_public_chat_snapshot(chat) if chat is not None else None
                    if snapshot is None or snapshot.source_type != "megagroup" or not snapshot.username:
                        continue
                    candidates.setdefault(int(snapshot.telegram_id), snapshot)
                    date = getattr(message, "date", now)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=UTC)
                    link = f"https://t.me/{snapshot.username}/{int(message.id)}"
                    text = " ".join(str(getattr(message, "message", "") or "").split())[:500]
                    hit = f"  запрос={query!r} | {date.isoformat()} | {link} | {text}"
                    bucket = discovery_hits.setdefault(int(snapshot.telegram_id), [])
                    if hit not in bucket:
                        bucket.append(hit)
                last = messages[-1]
                last_id = int(getattr(last, "id", 0) or 0)
                last_peer_id = _peer_id(last) or 0
                last_chat = chats.get(last_peer_id)
                last_date = getattr(last, "date", after)
                if last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=UTC)
                next_rate = getattr(result, "next_rate", None)
                next_offset_rate = int(next_rate if next_rate is not None else last_date.timestamp())
                cursor = (next_offset_rate, last_peer_id, last_id)
                if last_id <= 0 or last_peer_id <= 0 or cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                if last_chat is None:
                    break
                next_peer = _try_public_chat_snapshot(last_chat)
                if next_peer is None:
                    break
                resolved = await gateway._input_peer_or_empty(int(next_peer.telegram_id))
                if resolved is None:
                    break
                offset_rate = next_offset_rate
                offset_peer = resolved
                offset_id = last_id
                if next_rate is None and len(messages) < PAGE_SIZE:
                    break
                await asyncio.sleep(1)
            _save(lines + [f"Предварительно найдено: {len(candidates)}"])
            await asyncio.sleep(1)

        lines.append(f"Всего уникальных кандидатов: {len(candidates)}")
        qualified: list[str] = []
        for source_id, (telegram_id, source) in enumerate(candidates.items(), 1):
            username = str(getattr(source, "username"))
            lines.append("")
            lines.append(f"@{username}")
            lines.extend(discovery_hits.get(telegram_id, [])[:10])
            _save(lines)
            orders = await _three_manual_candidates(gateway, source, source_id, now)
            if len(orders) < 3:
                lines.append(f"  ОТКЛОНЁН: клиентских заказов от разных авторов: {len(orders)}")
                _save(lines)
                continue
            lines.append("  Три независимых заказа, требующие ручного подтверждения:")
            for published, permalink, text in orders:
                lines.append(f"  {published} {permalink}")
                lines.append(f"  {text}")
            result = await _check_megagroup(gateway, source, source_id, now)
            counters = result.get("counters")
            lines.append(f"  Проверка активности: {result['status']} | {result['reason']} | {counters}")
            if result["status"] == "qualified":
                qualified.append(username)
                lines.append("  ПРЕДВАРИТЕЛЬНО ПОЛНОСТЬЮ СООТВЕТСТВУЕТ — нужна ручная проверка текстов")
            _save(lines)
        lines.extend(["", "ИТОГ:", *[f"@{name}" for name in qualified]])
        _save(lines)
        print(f"CANDIDATES={len(candidates)} QUALIFIED={len(qualified)}", flush=True)
        return 0 if len(qualified) >= 3 else 1
    except GatewayFloodWait as exc:
        lines.append(f"ОСТАНОВЛЕНО TELEGRAM FLOOD WAIT ДО: {exc.until.isoformat()}")
        _save(lines)
        print(f"FLOOD_WAIT={exc.until.isoformat()}", flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001
        lines.append(f"ОШИБКА: {type(exc).__name__}: {exc}")
        _save(lines)
        print(f"ERROR={type(exc).__name__}: {exc}", flush=True)
        return 3
    finally:
        await gateway.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
