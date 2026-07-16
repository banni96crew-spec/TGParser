"""Notification outbox worker (NOT-005..NOT-008)."""

from __future__ import annotations

import html
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.security.secrets import require_env
from telegram_lead_discovery.settings.service import get_setting
from telegram_lead_discovery.storage.models import Lead, NotificationDelivery, NotificationOutbox

RETRY_OFFSETS_MINUTES = (0, 1, 5, 30, 120)
MAX_ATTEMPTS = 5
DELIVERABLE_EVENT_TYPES = frozenset({"hot_lead", "critical.system_event"})


class HttpClient(Protocol):
    async def post(self, url: str, *, json: dict[str, Any] | None = None) -> Any: ...


class HttpxResponseAdapter:
    def __init__(self, response: Any) -> None:
        self.status_code = getattr(response, "status_code", 0)
        self._response = response

    def json(self) -> dict[str, Any]:
        return self._response.json()


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def is_deliverable_event(outbox: NotificationOutbox) -> bool:
    if outbox.event_type == "hot_lead" and outbox.lead_id is not None:
        return True
    if outbox.incident_id is not None and outbox.lead_id is None:
        return outbox.event_type in DELIVERABLE_EVENT_TYPES or outbox.event_type.startswith(
            "critical."
        )
    return False


def _next_available_at(
    created_at: datetime,
    attempt_no: int,
    *,
    retry_after_seconds: int | None = None,
) -> datetime | None:
    """Absolute schedule from created_at; attempt_no is the completed failed attempt (1..4)."""
    if attempt_no >= MAX_ATTEMPTS:
        return None
    # Next attempt index in RETRY_OFFSETS_MINUTES (attempt 1 done → offset[1]=1 min, …).
    offset_minutes = RETRY_OFFSETS_MINUTES[min(attempt_no, len(RETRY_OFFSETS_MINUTES) - 1)]
    scheduled = created_at + timedelta(minutes=offset_minutes)
    if retry_after_seconds is not None and retry_after_seconds > 0:
        floored = datetime.now(UTC) + timedelta(seconds=retry_after_seconds)
        return max(scheduled, floored)
    return scheduled


async def claim_outbox(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> NotificationOutbox | None:
    clock = now or datetime.now(UTC)
    result = await session.execute(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.state.in_(("queued", "retry_wait")),
            or_(
                NotificationOutbox.available_at.is_(None),
                NotificationOutbox.available_at <= clock,
            ),
        )
        .order_by(NotificationOutbox.id.asc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.state = "delivering"
    await session.flush()
    return row


async def requeue_dead(
    session: AsyncSession,
    outbox_id: int,
) -> NotificationOutbox:
    """Manual retry: dead → queued once; resets automatic attempt counter (same row/key)."""
    row = await session.get(NotificationOutbox, outbox_id)
    if row is None:
        raise KeyError(f"outbox_not_found:{outbox_id}")
    if row.state != "dead":
        raise ValueError(f"outbox_not_dead:{row.state}")
    row.state = "queued"
    row.available_at = None
    row.automatic_attempt_count = 0
    row.manual_retry_count = int(getattr(row, "manual_retry_count", 0) or 0) + 1
    await session.flush()
    return row


async def _render_body(session: AsyncSession, outbox: NotificationOutbox) -> str:
    if outbox.lead_id is not None:
        lead = await session.get(Lead, outbox.lead_id)
        if lead is not None:
            return f"Hot lead #{lead.id} band={lead.band} category={lead.category}"
        return f"Hot lead #{outbox.lead_id}"
    return f"Critical incident {outbox.incident_id} type={outbox.event_type}"


async def deliver_outbox_item(
    session: AsyncSession,
    outbox: NotificationOutbox,
    *,
    client: Any,
    now: datetime | None = None,
) -> NotificationDelivery:
    clock = now or datetime.now(UTC)
    mode = await get_setting(session, "notifications.delivery_mode")
    if mode != "live":
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=1,
            status="skipped_shadow",
            error_code="shadow_mode",
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery

    if not is_deliverable_event(outbox):
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=1,
            status="dead",
            error_code="undeliverable_event_type",
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery

    attempt_no = int(getattr(outbox, "automatic_attempt_count", 0) or 0) + 1
    if attempt_no > MAX_ATTEMPTS:
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=attempt_no,
            status="dead",
            error_code="max_attempts",
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery

    outbox.automatic_attempt_count = attempt_no
    token = require_env("TG_BOT_TOKEN")
    chat_id = require_env("TG_NOTIFY_CHAT_ID")
    body = escape_html(await _render_body(session, outbox))[:4096]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": body,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = await client.post(url, json=payload)
        status_code = getattr(response, "status_code", None)
        if status_code is None and hasattr(response, "status"):
            status_code = response.status
        data = response.json() if hasattr(response, "json") else {}
        if callable(data):
            data = data()
    except TimeoutError:
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=attempt_no,
            status="dead",
            error_code="delivery_uncertain",
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery
    except Exception:  # noqa: BLE001 — treat as uncertain after request start
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=attempt_no,
            status="dead",
            error_code="delivery_uncertain",
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery

    if not isinstance(data, dict):
        outbox.state = "dead"
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=attempt_no,
            status="dead",
            error_code="delivery_uncertain",
            response_code=str(status_code or ""),
            attempted_at=clock,
        )
        session.add(delivery)
        await session.flush()
        return delivery

    ok = bool(data.get("ok"))
    if ok:
        tg_mid = None
        result = data.get("result")
        if isinstance(result, dict):
            tg_mid = result.get("message_id")
        delivery = NotificationDelivery(
            outbox_id=outbox.id,
            attempt_no=attempt_no,
            status="sent",
            response_code=str(status_code or 200),
            telegram_message_id=int(tg_mid) if tg_mid is not None else None,
            attempted_at=clock,
        )
        session.add(delivery)
        outbox.state = "sent"
        await session.flush()
        return delivery

    retry_after: int | None = None
    params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    if isinstance(params, dict) and params.get("retry_after") is not None:
        try:
            retry_after = int(params["retry_after"])
        except (TypeError, ValueError):
            retry_after = None
    if status_code == 429 and retry_after is None:
        try:
            retry_after = int(data.get("retry_after") or 0) or None
        except (TypeError, ValueError):
            retry_after = None

    if attempt_no >= MAX_ATTEMPTS:
        outbox.state = "dead"
        outbox.available_at = None
    else:
        outbox.state = "retry_wait"
        outbox.available_at = _next_available_at(
            outbox.created_at,
            attempt_no,
            retry_after_seconds=retry_after,
        )

    delivery = NotificationDelivery(
        outbox_id=outbox.id,
        attempt_no=attempt_no,
        status="error_response",
        response_code=str(status_code or ""),
        error_code="telegram_error",
        attempted_at=clock,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def process_one(
    session: AsyncSession,
    *,
    client: Any,
    now: datetime | None = None,
) -> NotificationDelivery | None:
    mode = await get_setting(session, "notifications.delivery_mode")
    if mode != "live":
        return None
    if not os.environ.get("TG_BOT_TOKEN") or not os.environ.get("TG_NOTIFY_CHAT_ID"):
        return None
    item = await claim_outbox(session, now=now)
    if item is None:
        return None
    return await deliver_outbox_item(session, item, client=client, now=now)


async def deliver_one(
    session: AsyncSession,
    *,
    client: Any,
    now: datetime | None = None,
) -> bool | None:
    """Claim one outbox row and deliver.

    Returns True on send, False on failed attempt, None if idle/shadow.
    """
    delivery = await process_one(session, client=client, now=now)
    if delivery is None:
        return None
    return delivery.status == "sent"
