from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.security.secrets import load_secret_presence, read_secret_presence
from telegram_lead_discovery.security.types import SecretPresenceSnapshot
from telegram_lead_discovery.settings.service import get_setting
from telegram_lead_discovery.storage.models import NotificationOutbox


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    inserted: bool
    skipped_reason: str | None = None
    row: NotificationOutbox | None = None


async def notifications_delivery_enabled(
    session: AsyncSession,
    *,
    delivery_mode: str | None = None,
    secret_presence: SecretPresenceSnapshot | None = None,
) -> bool:
    presence = secret_presence if secret_presence is not None else read_secret_presence()
    if not presence.notifications_ready:
        return False
    mode = delivery_mode
    if mode is None:
        mode = await get_setting(session, "notifications.delivery_mode")
    return mode == "live"


_ALLOWED_ENQUEUE_TYPES = frozenset({"hot_lead", "critical.system_event"})


def _enqueue_event_allowed(
    event_type: str,
    *,
    lead_id: int | None,
    incident_id: str | None,
) -> bool:
    if event_type == "hot_lead" and lead_id is not None and incident_id is None:
        return True
    if incident_id is not None and lead_id is None:
        return event_type in _ALLOWED_ENQUEUE_TYPES or event_type.startswith("critical.")
    return False


async def enqueue_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    idempotency_key: str,
    lead_id: int | None = None,
    incident_id: str | None = None,
    score_version: int | None = None,
    delivery_mode: str | None = None,
    secret_presence: SecretPresenceSnapshot | None = None,
) -> EnqueueResult:
    presence = secret_presence if secret_presence is not None else load_secret_presence()
    mode = delivery_mode
    if mode is None:
        try:
            mode = await get_setting(session, "notifications.delivery_mode")
        except KeyError:
            mode = "shadow"
    if mode != "live" or not presence.notifications_ready:
        return EnqueueResult(inserted=False, skipped_reason="shadow_or_missing_secrets")

    if not _enqueue_event_allowed(event_type, lead_id=lead_id, incident_id=incident_id):
        return EnqueueResult(inserted=False, skipped_reason="undeliverable_event_type")

    existing = await session.execute(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == idempotency_key)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return EnqueueResult(inserted=False, skipped_reason="duplicate_idempotency_key", row=row)

    row = NotificationOutbox(
        event_type=event_type,
        lead_id=lead_id,
        incident_id=incident_id,
        score_version=score_version,
        idempotency_key=idempotency_key,
        state="queued",
    )
    session.add(row)
    await session.flush()
    return EnqueueResult(inserted=True, row=row)


async def enqueue_hot_lead(
    session: AsyncSession,
    *,
    lead_id: int,
    score_version: int,
) -> NotificationOutbox | None:
    key = f"hot_lead:{lead_id}:{score_version}"
    result = await enqueue_outbox(
        session,
        event_type="hot_lead",
        idempotency_key=key,
        lead_id=lead_id,
        incident_id=None,
        score_version=score_version,
    )
    return result.row if result.inserted or result.row is not None else None


async def enqueue_critical(
    session: AsyncSession,
    *,
    event_type: str,
    incident_id: str,
) -> NotificationOutbox | None:
    result = await enqueue_outbox(
        session,
        event_type=event_type,
        idempotency_key=f"{event_type}:{incident_id}",
        lead_id=None,
        incident_id=incident_id,
    )
    return result.row if result.inserted or result.row is not None else None
