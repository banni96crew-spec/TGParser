"""One-off free global public-post search, filtered to public megagroups."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telethon.tl.functions.channels import SearchPostsRequest
from telethon.tl.types import InputPeerEmpty

from direct_group_message_search import QUERIES, _peer_id
from find_one_qualified_chat import _check_megagroup
from global_client_message_search import _three_manual_candidates
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
)
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


OUTPUT = Path(__file__).resolve().parent / "direct_public_post_group_search.txt"
PAGE_SIZE = 100


def _save(lines: list[str]) -> None:
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    now = datetime.now(UTC)
    after = now - timedelta(days=30)
    lines = [
        "ГЛОБАЛЬНЫЙ ПОИСК ПУБЛИЧНЫХ СООБЩЕНИЙ TELEGRAM",
        f"Запуск UTC: {now.isoformat()}",
        f"Период проверки: {after.isoformat()} — {now.isoformat()}",
        "Оплата Stars: запрещена; используются только бесплатные запросы",
        "",
        "КАНДИДАТЫ:",
    ]
    candidates: dict[int, object] = {}
    discovery_hits: dict[int, list[str]] = {}
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))
    try:
        await gateway.connect()
        for query in QUERIES:
            quota = await gateway.check_public_post_search_quota(query)
            lines.append(
                f"ЗАПРОС {query!r}: free={quota.free_slot_available}, "
                f"premium={quota.premium_required}, stars={quota.stars_amount}"
            )
            _save(lines)
            if quota.premium_required or not quota.free_slot_available:
                lines.append("ОСТАНОВЛЕНО: бесплатные глобальные запросы недоступны")
                break
            offset_rate = 0
            offset_peer: object = InputPeerEmpty()
            offset_id = 0
            seen_cursors: set[tuple[int, int, int]] = set()
            while True:
                result = await gateway._invoke(SearchPostsRequest(
                    offset_rate=offset_rate,
                    offset_peer=offset_peer,
                    offset_id=offset_id,
                    limit=PAGE_SIZE,
                    hashtag=None,
                    query=query,
                    allow_paid_stars=None,
                ))
                messages = list(getattr(result, "messages", None) or ())
                chats = {
                    int(chat.id): chat
                    for chat in (getattr(result, "chats", None) or ())
                    if getattr(chat, "id", None) is not None
                }
                if not messages:
                    break
                oldest = now
                for message in messages:
                    date = getattr(message, "date", now)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=UTC)
                    oldest = min(oldest, date)
                    if date < after:
                        continue
                    chat_id = _peer_id(message)
                    chat = chats.get(chat_id or 0)
                    snapshot = _try_public_chat_snapshot(chat) if chat is not None else None
                    if snapshot is None or snapshot.source_type != "megagroup" or not snapshot.username:
                        continue
                    candidates.setdefault(int(snapshot.telegram_id), snapshot)
                    text = " ".join(str(getattr(message, "message", "") or "").split())[:500]
                    link = f"https://t.me/{snapshot.username}/{int(message.id)}"
                    hit = f"  запрос={query!r} | {date.isoformat()} | {link} | {text}"
                    bucket = discovery_hits.setdefault(int(snapshot.telegram_id), [])
                    if hit not in bucket:
                        bucket.append(hit)
                if oldest < after:
                    break
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
                if last_id <= 0 or last_peer_id <= 0 or cursor in seen_cursors or last_chat is None:
                    break
                seen_cursors.add(cursor)
                snapshot = _try_public_chat_snapshot(last_chat)
                if snapshot is None:
                    break
                resolved = await gateway._input_peer_or_empty(int(snapshot.telegram_id))
                if resolved is None:
                    break
                offset_rate = next_offset_rate
                offset_peer = resolved
                offset_id = last_id
                if next_rate is None and len(messages) < PAGE_SIZE:
                    break
                await asyncio.sleep(1)
            await asyncio.sleep(1)

        lines.append(f"Уникальных публичных супергрупп: {len(candidates)}")
        qualified: list[str] = []
        for source_id, (telegram_id, source) in enumerate(candidates.items(), 1):
            username = str(getattr(source, "username"))
            lines.extend(["", f"@{username}"])
            lines.extend(discovery_hits.get(telegram_id, [])[:20])
            _save(lines)
            orders = await _three_manual_candidates(gateway, source, source_id, now)
            if len(orders) < 3:
                lines.append(f"  ОТКЛОНЁН: клиентских заказов от разных авторов: {len(orders)}")
                _save(lines)
                continue
            lines.append("  Три независимых заказа, требующие ручного подтверждения:")
            for published, permalink, text in orders:
                lines.extend([f"  {published} {permalink}", f"  {text}"])
            result = await _check_megagroup(gateway, source, source_id, now)
            lines.append(
                f"  Активность: {result['status']} | {result['reason']} | "
                f"{result.get('counters')}"
            )
            if result["status"] == "qualified":
                qualified.append(username)
                lines.append("  ПРЕДВАРИТЕЛЬНО СООТВЕТСТВУЕТ — нужна ручная проверка текстов")
            _save(lines)
        lines.extend(["", "ИТОГ:", *[f"@{name}" for name in qualified]])
        _save(lines)
        print(f"CANDIDATES={len(candidates)} QUALIFIED={len(qualified)}", flush=True)
        return 0 if len(qualified) >= 3 else 1
    except (
        GatewayFloodWait,
        GatewayPremiumRequired,
        GatewaySearchQuotaExhausted,
    ) as exc:
        lines.append(f"ОСТАНОВЛЕНО TELEGRAM: {type(exc).__name__}: {exc}")
        _save(lines)
        print(f"STOPPED={type(exc).__name__}: {exc}", flush=True)
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
