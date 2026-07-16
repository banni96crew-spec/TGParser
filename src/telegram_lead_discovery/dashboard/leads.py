"""Lead inbox queries and status triage for the local dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import Lead, LeadStatusHistory

ALLOWED_STATUSES = frozenset(
    {
        "new",
        "reviewed",
        "contacted",
        "won",
        "lost",
        "ignored",
        "source_deleted",
    }
)
DEFAULT_INBOX_LIMIT = 50
MAX_INBOX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class InboxPage:
    leads: list[Lead]
    next_cursor: str | None
    limit: int


def encode_cursor(*, last_activity_at: datetime, lead_id: int) -> str:
    return quote(f"{last_activity_at.isoformat()}|{lead_id}", safe="")


def decode_cursor(raw: str) -> tuple[datetime, int]:
    decoded = unquote(raw)
    stamp, lead_id_s = decoded.rsplit("|", 1)
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when, int(lead_id_s)


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_INBOX_LIMIT
    return max(1, min(int(limit), MAX_INBOX_LIMIT))


async def list_inbox_leads(
    session: AsyncSession,
    *,
    band: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> InboxPage:
    page_size = clamp_limit(limit)
    query = select(Lead).order_by(Lead.last_activity_at.desc(), Lead.id.desc())
    if band:
        query = query.where(Lead.band == band)
    else:
        query = query.where(Lead.band.in_(("hot", "warm", "cold")))
    if cursor:
        cursor_at, cursor_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Lead.last_activity_at < cursor_at,
                and_(Lead.last_activity_at == cursor_at, Lead.id < cursor_id),
            )
        )
    query = query.limit(page_size + 1)
    rows = list((await session.execute(query)).scalars().all())
    next_cursor = None
    if len(rows) > page_size:
        last = rows[page_size - 1]
        next_cursor = encode_cursor(
            last_activity_at=last.last_activity_at, lead_id=last.id
        )
        rows = rows[:page_size]
    return InboxPage(leads=rows, next_cursor=next_cursor, limit=page_size)


async def update_lead_status(
    session: AsyncSession,
    *,
    lead_id: int,
    to_status: str,
    note: str | None = None,
    now: datetime | None = None,
) -> Lead:
    if to_status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid status: {to_status}")
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise KeyError(lead_id)
    clock = now or datetime.now(UTC)
    from_status = lead.status
    if from_status == to_status:
        return lead
    lead.status = to_status
    lead.updated_at = clock
    lead.last_activity_at = clock
    session.add(
        LeadStatusHistory(
            lead_id=lead.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_at=clock,
        )
    )
    await session.flush()
    return lead
