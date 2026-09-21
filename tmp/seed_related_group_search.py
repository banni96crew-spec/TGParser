"""One-off related-source discovery and strict megagroup qualification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from find_one_qualified_chat import _check_megagroup
from global_client_message_search import _three_manual_candidates
from telegram_lead_discovery.collector.adapter.telethon_gateway import TelethonTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    PublicSourceRef,
    SourceRef,
)
from telegram_lead_discovery.infrastructure.windows_proxy import resolve_telegram_connection


SEEDS = (
    "python_chatt",
    "freelancerscha",
    "frilans_na_legke",
    "digitaltender",
    "TRemoters",
    "n8n_community",
    "coding_ru",
    "js_ru",
    "nodejs_ru",
)
OUTPUT = Path(__file__).resolve().parent / "seed_related_group_search.txt"


def _ref(source: object, source_id: int) -> SourceRef:
    return SourceRef(
        schema_version=1,
        source_id=source_id,
        telegram_id=int(getattr(source, "telegram_id")),
        username=str(getattr(source, "username")),
        access_hash=getattr(source, "access_hash"),
    )


def _save(lines: list[str]) -> None:
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> int:
    now = datetime.now(UTC)
    lines = [
        "ПОИСК ПО СМЕЖНЫМ ИСТОЧНИКАМ TELEGRAM",
        f"Запуск UTC: {now.isoformat()}",
        "Глубина рекомендаций: 3 уровня",
        "",
        "СИДЫ:",
        *[f"@{seed}" for seed in SEEDS],
        "",
        "НАЙДЕННЫЕ ИСТОЧНИКИ:",
    ]
    found: dict[int, tuple[object, set[str]]] = {}
    gateway = TelethonTelegramGateway(connection_config=resolve_telegram_connection("auto"))

    def remember(source: object, origin: str) -> None:
        telegram_id = int(getattr(source, "telegram_id"))
        if telegram_id in found:
            found[telegram_id][1].add(origin)
        else:
            found[telegram_id] = (source, {origin})

    try:
        await gateway.connect()
        frontier: list[object] = []
        for seed in SEEDS:
            try:
                source = await gateway.resolve_public_source(
                    PublicSourceRef(schema_version=1, username_or_url=seed)
                )
                remember(source, f"seed:@{seed}")
                frontier.append(source)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"@{seed} | ошибка разрешения: {type(exc).__name__}: {exc}")
            _save(lines)
            await asyncio.sleep(1)

        visited: set[int] = set()
        for depth in (1, 2, 3):
            next_frontier: list[object] = []
            for source_id, source in enumerate(frontier, 1):
                telegram_id = int(getattr(source, "telegram_id"))
                if telegram_id in visited:
                    continue
                visited.add(telegram_id)
                source_ref = _ref(source, source_id)
                try:
                    recommendations = await gateway.get_recommendations(source_ref, 100)
                    for candidate in recommendations:
                        remember(candidate, f"recommendation:d{depth}:@{getattr(source, 'username')}")
                        next_frontier.append(candidate)
                except Exception as exc:  # noqa: BLE001
                    lines.append(
                        f"@{getattr(source, 'username')} | ошибка рекомендаций: "
                        f"{type(exc).__name__}: {exc}"
                    )
                try:
                    linked = await gateway.get_linked_discussion(source_ref)
                    if linked is not None:
                        remember(linked, f"linked:d{depth}:@{getattr(source, 'username')}")
                        next_frontier.append(linked)
                except Exception as exc:  # noqa: BLE001
                    lines.append(
                        f"@{getattr(source, 'username')} | ошибка связанного чата: "
                        f"{type(exc).__name__}: {exc}"
                    )
                _save(lines + [f"Найдено уникальных источников: {len(found)}"])
                await asyncio.sleep(1)
            frontier = next_frontier

        for source, origins in found.values():
            username = str(getattr(source, "username", "") or "")
            source_type = str(getattr(source, "source_type", "unknown"))
            lines.append(
                f"@{username} | {source_type} | источники: {', '.join(sorted(origins))}"
            )
        lines.append("")
        lines.append("ПРОВЕРКА ПУБЛИЧНЫХ СУПЕРГРУПП:")
        _save(lines)

        qualified: list[str] = []
        megagroups = [item[0] for item in found.values() if getattr(item[0], "source_type", None) == "megagroup" and getattr(item[0], "username", None)]
        for source_id, source in enumerate(megagroups, 1):
            username = str(getattr(source, "username"))
            orders = await _three_manual_candidates(gateway, source, source_id, now)
            if len(orders) < 3:
                lines.append(f"@{username} | ОТКЛОНЁН | заказов от разных авторов: {len(orders)}")
                _save(lines)
                continue
            lines.append(f"@{username} | три заказа найдены")
            for published, permalink, text in orders:
                lines.extend([f"  {published} {permalink}", f"  {text}"])
            result = await _check_megagroup(gateway, source, source_id, now)
            lines.append(
                f"@{username} | активность: {result['status']} | {result['reason']} | "
                f"{result.get('counters')}"
            )
            if result["status"] == "qualified":
                qualified.append(username)
                lines.append("  ПРЕДВАРИТЕЛЬНО СООТВЕТСТВУЕТ — нужна ручная проверка заказов")
            _save(lines)
        lines.extend(["", "ИТОГ:", *[f"@{name}" for name in qualified]])
        _save(lines)
        print(
            f"FOUND={len(found)} MEGAGROUPS={len(megagroups)} QUALIFIED={len(qualified)}",
            flush=True,
        )
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
