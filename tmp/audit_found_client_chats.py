"""Audit every source found by graph run 41; never performs global search."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    HistoryRequest,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.catalog import ACTIVE_SEED_RULES
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.infrastructure.paths import database_path
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

RUN_ID = 41
PAGE_SIZE = 100
SOURCE_CAP = 1500
OUTPUT = Path(__file__).resolve().parent / "found_chats_qualification.txt"
PROGRESS = Path(__file__).resolve().parent / "found_chats_qualification.progress.json"
RULE_CHECKSUM = catalog_checksum(ACTIVE_SEED_RULES)


def _source_rows() -> list[dict[str, object]]:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT s.id, s.username_normalized, s.title, s.telegram_id,
                            s.access_hash, s.source_type
            FROM source_discovery_events e
            JOIN telegram_sources s ON s.id=e.source_id
            WHERE e.run_id=? AND e.outcome IN ('candidate','merged')
            ORDER BY s.username_normalized
            """,
            (RUN_ID,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _safe_summary(text: str) -> str:
    return " ".join(text.split())[:180]


_EXECUTOR_OR_JOB = re.compile(
    r"(?:"
    r"\b(?:я|мы)\s+(?:веб[- ]?дизайнер|разработчик|программист|технический специалист|фрилансер)\b|"
    r"\b(?:разрабатываю|создаю|делаю|настраиваю|предлагаю)\b|"
    r"\b(?:ищу|возьму)\s+(?:заказ|заказы|проект|проекты|клиента|клиентов)\b|"
    r"\b(?:мои услуги|портфолио|готов выполнить|готов взяться|беру заказы)\b|"
    r"#(?:помогу|вебдизайнер|разработчик|программист|техспец)\b|"
    r"\b(?:вакансия|зарплата|резюме|отклик|полная занятость|частичная занятость|в штат)\b|"
    r"\bищем\s+(?:менеджера|сотрудника|стажера|стажёра)\b"
    r")",
    re.IGNORECASE,
)

_CLIENT_INTENT = re.compile(
    r"(?:"
    r"\b(?:ищу|ищем)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)\b|"
    r"\b(?:нужен|нужна|нужны|требуется)\s+(?:разработчик|программист|специалист|исполнитель|подрядчик|команда)\b|"
    r"\b(?:нужен|нужна|нужны|требуется)\s+(?:сайт|лендинг|бот|чат[- ]?бот|парсер|автоматизация|интеграция|интернет[- ]?магазин)\b|"
    r"\b(?:кто|кто-нибудь)\s+(?:может|сможет|готов)\s+(?:сделать|разработать|настроить|написать|создать|подключить|интегрировать)\b|"
    r"\b(?:нужно|необходимо|требуется)\s+(?:сделать|разработать|настроить|написать|создать|подключить|интегрировать)\b|"
    r"\b(?:посоветуйте|порекомендуйте)\s+(?:разработчика|программиста|специалиста|исполнителя|подрядчика|команду)\b"
    r")",
    re.IGNORECASE,
)


def _is_strict_client_request(text: str, category: str | None) -> bool:
    if category not in {"direct_order", "contractor_search", "recommendation_request"}:
        return False
    normalized = " ".join(text.split())
    return not _EXECUTOR_OR_JOB.search(normalized) and bool(_CLIENT_INTENT.search(normalized))


async def _audit_chat(
    gateway: TelethonTelegramGateway,
    source: dict[str, object],
    reference_at: datetime,
) -> dict[str, object]:
    telegram_id = int(source["telegram_id"])
    accumulator = ActiveChatAccumulator(reference_at=reference_at)
    offset_id = 0
    scanned = 0
    evidence: list[dict[str, object]] = []
    rejected_candidates: list[dict[str, object]] = []
    evidence_authors: set[str] = set()
    stop_reason = "source_cap"
    while scanned < SOURCE_CAP:
        request = HistoryRequest(
            schema_version=1,
            source_id=int(source["id"]),
            peer=TelegramPeerRef(
                schema_version=1,
                telegram_peer_id=telegram_id,
                access_hash=int(source["access_hash"]),
                username_normalized=str(source["username_normalized"]),
            ),
            limit=min(PAGE_SIZE, SOURCE_CAP - scanned),
            purpose="scouting_verification",
            continuation_cursor=str(offset_id) if offset_id else None,
        )
        page = [message async for message in gateway.iter_history(request)]
        if not page:
            stop_reason = "history_exhausted"
            break
        reached_window = False
        for dto in page:
            published = dto.published_at.astimezone(UTC)
            if published < reference_at - timedelta(days=30):
                reached_window = True
                stop_reason = "window_complete"
                break
            scanned += 1
            offset_id = int(dto.telegram_message_id)
            _, normalized_hash, detection = qualify_excerpt_text(
                dto.text or "",
                detect_fn=lambda text: detect(
                    text,
                    rules=ACTIVE_SEED_RULES,
                    rule_set_checksum=RULE_CHECKSUM,
                ),
            )
            author_kind = dto.author_kind
            author_key = None
            if author_kind == "user" and dto.author_peer_id is not None:
                author_key = source_scoped_author_key(telegram_id, dto.author_peer_id)
            elif author_kind == "user":
                author_kind = "unknown"
            strict_client_request = _is_strict_client_request(
                dto.text or "", detection.category
            )
            targeted_category = detection.category in {
                "direct_order",
                "contractor_search",
                "recommendation_request",
            }
            if targeted_category and not strict_client_request:
                rejected_candidates.append(
                    {
                        "date": published.date().isoformat(),
                        "link": dto.permalink,
                        "category": detection.category,
                        "summary": _safe_summary(dto.text or ""),
                    }
                )
            active_message = ActiveChatMessage(
                telegram_message_id=int(dto.telegram_message_id),
                published_at=published,
                normalized_hash=normalized_hash,
                author_kind=author_kind,
                author_key=author_key,
                detection_category=(detection.category if strict_client_request else None),
                service_profiles=(
                    tuple(detection.service_profiles) if strict_client_request else ()
                ),
                hard_exclusion=(
                    detection.hard_exclusion
                    or ("strict_non_client_intent" if targeted_category else None)
                ),
            )
            countable = accumulator.consume(active_message)
            if countable and author_key and author_key not in evidence_authors:
                evidence_authors.add(author_key)
                evidence.append(
                    {
                        "date": published.date().isoformat(),
                        "link": dto.permalink,
                        "category": detection.category,
                        "services": list(detection.service_profiles),
                        "summary": _safe_summary(dto.text or ""),
                    }
                )
            if all(active_chat_thresholds(accumulator.counters(), reference_at=reference_at).values()):
                stop_reason = "quality_reached"
                reached_window = True
                break
        if reached_window:
            break
        if len(page) < request.limit:
            stop_reason = "history_exhausted"
            break
        await asyncio.sleep(1)

    counters = accumulator.counters()
    thresholds = active_chat_thresholds(counters, reference_at=reference_at)
    return {
        **source,
        "status": "full" if all(thresholds.values()) else "partial",
        "scanned": scanned,
        "stop_reason": stop_reason,
        "counters": asdict(counters),
        "thresholds": thresholds,
        "evidence": evidence[:3],
        "rejected_candidates": rejected_candidates[:50],
    }


def _metric_line(item: dict[str, object]) -> str:
    counters = item["counters"]
    assert isinstance(counters, dict)
    latest = counters["latest_client_request_at"]
    if isinstance(latest, datetime):
        latest = latest.date().isoformat()
    return (
        f"@{item['username_normalized']} — {item['title']} | "
        f"сообщения 14д: {counters['activity_message_count']}/100; "
        f"дни: {counters['activity_active_day_count']}/10; "
        f"авторы: {counters['activity_distinct_author_count']}/20; "
        f"запросы 30д: {counters['client_request_count']}/3; "
        f"авторы запросов: {counters['client_request_author_count']}/3; "
        f"последний запрос: {latest or 'нет'}; "
        f"проверено сообщений: {item['scanned']}; завершение: {item['stop_reason']}"
    )


def _write_report(rows: list[dict[str, object]], reference_at: datetime) -> None:
    full = [row for row in rows if row["status"] == "full"]
    partial = [row for row in rows if row["status"] == "partial"]
    rejected = [row for row in rows if row["status"] == "rejected"]
    lines = [
        "КВАЛИФИКАЦИЯ ЧАТОВ, НАЙДЕННЫХ ГРАФОВЫМ ОБХОДОМ",
        f"Дата проверки UTC: {reference_at.isoformat()}",
        f"Исходный графовый прогон: {RUN_ID}",
        "Глобальный поиск: НЕ ИСПОЛЬЗОВАЛСЯ",
        f"Всего источников: {len(rows)}; полностью: {len(full)}; частично: {len(partial)}; не соответствует: {len(rejected)}",
        "",
        "1. ПОЛНОСТЬЮ СООТВЕТСТВУЕТ КРИТЕРИЯМ",
    ]
    if not full:
        lines.append("(нет)")
    for item in full:
        lines.append(_metric_line(item))
        evidence = item["evidence"]
        assert isinstance(evidence, list)
        for number, proof in enumerate(evidence, 1):
            lines.append(
                f"  Доказательство {number}: {proof['date']} | {proof['link']} | "
                f"{proof['category']} | {', '.join(proof['services'])} | {proof['summary']}"
            )

    lines.extend(["", "2. ЧАСТИЧНО СООТВЕТСТВУЕТ"])
    if not partial:
        lines.append("(нет)")
    for item in partial:
        lines.append(_metric_line(item))
        thresholds = item["thresholds"]
        assert isinstance(thresholds, dict)
        missing = [name for name, passed in thresholds.items() if not passed]
        lines.append("  Не выполнено: " + ", ".join(missing))
        evidence = item["evidence"]
        assert isinstance(evidence, list)
        for number, proof in enumerate(evidence, 1):
            lines.append(
                f"  Найденный запрос {number}: {proof['date']} | {proof['link']} | "
                f"{proof['category']} | {', '.join(proof['services'])} | {proof['summary']}"
            )

    lines.extend(["", "3. НЕ СООТВЕТСТВУЕТ"])
    if not rejected:
        lines.append("(нет)")
    for item in rejected:
        lines.append(
            f"@{item['username_normalized']} — {item['title']} | причина: "
            f"тип {item['source_type']}, а обязателен публичный megagroup"
        )
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    reference_at = datetime.now(UTC)
    sources = _source_rows()
    results: list[dict[str, object]] = [
        {**source, "status": "rejected", "reason": "not_megagroup"}
        for source in sources
        if source["source_type"] != "megagroup"
    ]
    chats = [source for source in sources if source["source_type"] == "megagroup"]
    gateway = TelethonTelegramGateway(
        connection_config=resolve_telegram_connection("auto")
    )
    await gateway.connect()
    try:
        for index, source in enumerate(chats, 1):
            try:
                result = await _audit_chat(gateway, source, reference_at)
            except GatewayFloodWait as exc:
                PROGRESS.write_text(
                    json.dumps(results, ensure_ascii=False, default=str, indent=2),
                    encoding="utf-8",
                )
                print(f"FLOOD_WAIT until={exc.until.isoformat()}", flush=True)
                return 2
            results.append(result)
            PROGRESS.write_text(
                json.dumps(results, ensure_ascii=False, default=str, indent=2),
                encoding="utf-8",
            )
            print(
                f"[{index}/{len(chats)}] @{source['username_normalized']} "
                f"status={result['status']} counters={result['counters']}",
                flush=True,
            )
    finally:
        await gateway.disconnect()
    results.sort(key=lambda row: str(row["username_normalized"]))
    _write_report(results, reference_at)
    print(f"DONE {OUTPUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
