"""Safe CSV export helpers for inbox leads (UI-012)."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.storage.models import (
    Lead,
    LeadScore,
    LeadScoreComponent,
    TelegramAuthor,
    TelegramMessage,
    TelegramSource,
)

EXPORT_COLUMNS = (
    "lead_id",
    "published_at",
    "category",
    "score",
    "band",
    "status",
    "source_title",
    "source_username",
    "author_username",
    "text",
    "permalink",
    "reasons",
)
MAX_EXPORT_ROWS = 10_000
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def protect_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        return "'" + text
    return text


@dataclass(frozen=True, slots=True)
class ExportPreview:
    row_count: int
    columns: tuple[str, ...]
    band_filter: str | None


async def count_export_rows(
    session: AsyncSession,
    *,
    band: str | None = None,
) -> int:
    query = select(Lead)
    if band:
        query = query.where(Lead.band == band)
    else:
        query = query.where(Lead.band.in_(("hot", "warm", "cold")))
    result = await session.execute(query)
    return len(list(result.scalars().all()))


async def build_export_rows(
    session: AsyncSession,
    *,
    band: str | None = None,
    limit: int = MAX_EXPORT_ROWS,
) -> list[dict[str, str]]:
    cap = min(max(limit, 1), MAX_EXPORT_ROWS)
    query = (
        select(Lead)
        .order_by(Lead.last_activity_at.desc(), Lead.id.desc())
        .limit(cap)
    )
    if band:
        query = query.where(Lead.band == band)
    else:
        query = query.where(Lead.band.in_(("hot", "warm", "cold")))
    leads = list((await session.execute(query)).scalars().all())
    rows: list[dict[str, str]] = []
    for lead in leads:
        message = await session.get(TelegramMessage, lead.canonical_message_id)
        source: TelegramSource | None = None
        author: TelegramAuthor | None = None
        if message is not None:
            source = await session.get(TelegramSource, message.source_id)
            if message.author_id is not None:
                author = await session.get(TelegramAuthor, message.author_id)
        score_total = ""
        reasons = ""
        if lead.current_score_id is not None:
            score = await session.get(LeadScore, lead.current_score_id)
            if score is not None:
                score_total = str(score.total)
                comps = list(
                    (
                        await session.execute(
                            select(LeadScoreComponent).where(
                                LeadScoreComponent.lead_score_id == score.id
                            )
                        )
                    ).scalars()
                )
                reasons = "; ".join(
                    f"{c.dimension}:{c.reason_ru}" for c in comps if c.reason_ru
                )
        rows.append(
            {
                "lead_id": str(lead.id),
                "published_at": (
                    message.published_at.isoformat() if message is not None else ""
                ),
                "category": lead.category,
                "score": score_total,
                "band": lead.band,
                "status": lead.status,
                "source_title": source.title if source is not None else "",
                "source_username": (
                    source.username_normalized if source is not None else ""
                )
                or "",
                "author_username": (author.username if author is not None else "") or "",
                "text": message.original_text if message is not None else "",
                "permalink": (message.permalink if message is not None else "") or "",
                "reasons": reasons,
            }
        )
    return rows


def render_csv(rows: Sequence[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(EXPORT_COLUMNS),
        delimiter=";",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({col: protect_csv_cell(row.get(col, "")) for col in EXPORT_COLUMNS})
    return buffer.getvalue()


def write_export_file(
    rows: Sequence[dict[str, str]],
    *,
    exports_dir: Path | None = None,
    clock: datetime | None = None,
) -> Path:
    paths = ensure_app_directories(resolve_app_paths())
    target_dir = exports_dir or paths.exports_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = (clock or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    path = target_dir / f"telegram-leads-{stamp}.csv"
    content = "\ufeff" + render_csv(rows)
    path.write_text(content, encoding="utf-8", newline="")
    return path
