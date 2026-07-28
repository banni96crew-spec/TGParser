"""Operator-controlled source lifecycle transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import PublicSourceRef, TelegramGateway
from telegram_lead_discovery.collector.service import enqueue_initial_backfill
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    SourceApprovalEvent,
    TelegramSource,
)

REJECT_REASON_CODES = frozenset(
    {"off_topic", "low_signal", "duplicate_manual", "not_needed"}
)


class SourceLifecycleError(ValueError):
    """Invalid source lifecycle transition or reason."""


async def approve_source(
    session: AsyncSession,
    *,
    source_id: int,
    gateway: TelegramGateway,
    note: str | None = None,
) -> TelegramSource:
    source = await session.get(TelegramSource, source_id)
    if source is None:
        raise KeyError(source_id)
    if source.lifecycle_state not in {"candidate", "approved"}:
        raise ValueError(f"invalid_transition:{source.lifecycle_state}")

    from_state = source.lifecycle_state
    ref: PublicSourceRef | int
    if source.telegram_id is not None:
        ref = source.telegram_id
    else:
        ref = PublicSourceRef(
            schema_version=1,
            username_or_url=source.username_normalized or "",
        )
    # Release SQLite lock before Telethon I/O (one writer; busy_timeout=5000).
    await session.commit()

    snap = await gateway.validate_source(ref)

    source = await session.get(TelegramSource, source_id)
    if source is None:
        raise KeyError(source_id)
    if source.lifecycle_state not in {"candidate", "approved"}:
        raise ValueError(f"invalid_transition:{source.lifecycle_state}")

    now = datetime.now(UTC)
    source.telegram_id = snap.telegram_id
    source.username_normalized = snap.username.lower()
    source.title = snap.title
    source.source_type = snap.source_type
    source.public_url = snap.public_url
    source.lifecycle_state = "monitoring"
    source.approved_at = source.approved_at or now
    source.monitoring_started_at = now
    source.access_error_code = None

    session.add(
        SourceApprovalEvent(
            event_id=str(uuid.uuid4()),
            source_id=source.id,
            from_state=from_state,
            to_state="monitoring",
            reason_code="operator_approve",
            trigger="ui",
            note=note,
        )
    )
    checkpoint = await session.get(CollectorCheckpoint, source.id)
    if checkpoint is None:
        session.add(CollectorCheckpoint(source_id=source.id))
    await enqueue_initial_backfill(session, source.id)
    await session.flush()
    return source


async def _transition_source(
    session: AsyncSession,
    *,
    source_id: int,
    allowed_from: set[str],
    to_state: str,
    reason_code: str,
    note: str | None = None,
    trigger: str = "ui",
) -> TelegramSource:
    """Idempotent lifecycle transition: same target returns current row (SRC-012)."""
    source = await session.get(TelegramSource, source_id)
    if source is None:
        raise KeyError(source_id)
    if source.lifecycle_state == to_state:
        return source
    if source.lifecycle_state not in allowed_from:
        raise SourceLifecycleError(
            f"invalid_transition:{source.lifecycle_state}->{to_state}"
        )
    from_state = source.lifecycle_state
    now = datetime.now(UTC)
    source.lifecycle_state = to_state
    source.updated_at = now
    if to_state == "disabled":
        source.disabled_at = now
    if to_state == "monitoring" and source.monitoring_started_at is None:
        source.monitoring_started_at = now
    session.add(
        SourceApprovalEvent(
            event_id=str(uuid.uuid4()),
            source_id=source.id,
            from_state=from_state,
            to_state=to_state,
            reason_code=reason_code,
            trigger=trigger,
            note=note,
        )
    )
    await session.flush()
    return source


async def reject_source(
    session: AsyncSession,
    *,
    source_id: int,
    reason_code: str,
    note: str | None = None,
) -> TelegramSource:
    if reason_code not in REJECT_REASON_CODES:
        raise SourceLifecycleError(f"invalid_reject_reason:{reason_code}")
    return await _transition_source(
        session,
        source_id=source_id,
        allowed_from={"candidate"},
        to_state="rejected",
        reason_code=reason_code,
        note=note,
    )


async def reconsider_source(
    session: AsyncSession,
    *,
    source_id: int,
    note: str | None = None,
) -> TelegramSource:
    """ReconsiderSource: rejected → candidate (distinct from ReconsiderDismissSuppress)."""
    return await _transition_source(
        session,
        source_id=source_id,
        allowed_from={"rejected"},
        to_state="candidate",
        reason_code="operator_reconsider",
        note=note,
    )


async def pause_source(
    session: AsyncSession,
    *,
    source_id: int,
    note: str | None = None,
) -> TelegramSource:
    return await _transition_source(
        session,
        source_id=source_id,
        allowed_from={"monitoring"},
        to_state="paused",
        reason_code="operator_pause",
        note=note,
    )


async def resume_source(
    session: AsyncSession,
    *,
    source_id: int,
    note: str | None = None,
) -> TelegramSource:
    return await _transition_source(
        session,
        source_id=source_id,
        allowed_from={"paused"},
        to_state="monitoring",
        reason_code="operator_resume",
        note=note,
    )


async def disable_source(
    session: AsyncSession,
    *,
    source_id: int,
    note: str | None = None,
) -> TelegramSource:
    return await _transition_source(
        session,
        source_id=source_id,
        allowed_from={"monitoring", "paused", "inaccessible"},
        to_state="disabled",
        reason_code="operator_disabled",
        note=note,
    )
