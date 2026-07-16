"""Collector service: envelopes, checkpoints, backfill/reconciliation jobs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    HistoryRequest,
    TelegramGateway,
    TelegramMessageDTO,
)
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    TelegramEventEnvelope,
    TelegramSource,
)


def _event_id(source_id: int, event_type: str, message_id: int, observed_at: datetime) -> str:
    return f"{source_id}:{event_type}:{message_id}:{observed_at.isoformat()}"


async def persist_message_envelope(
    session: AsyncSession,
    *,
    source_id: int,
    dto: TelegramMessageDTO,
    collection_mode: str,
    event_type: str = "message_new",
    observed_at: datetime | None = None,
) -> TelegramEventEnvelope:
    clock = observed_at or datetime.now(UTC)
    edit_key = "0"
    if event_type == "message_edited" and dto.edited_at is not None:
        edit_key = dto.edited_at.isoformat()
    event_id = _event_id(source_id, event_type, dto.telegram_message_id, clock)
    existing = await session.execute(
        select(TelegramEventEnvelope).where(TelegramEventEnvelope.event_id == event_id)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row
    payload = {
        "text": dto.text,
        "published_at": dto.published_at.isoformat(),
        "edited_at": dto.edited_at.isoformat() if dto.edited_at else None,
        "author_peer_id": dto.author_peer_id,
        "author_username": dto.author_username,
        "permalink": dto.permalink,
    }
    row = TelegramEventEnvelope(
        event_id=event_id,
        event_type=event_type,
        source_id=source_id,
        telegram_message_id=dto.telegram_message_id,
        edit_key=edit_key,
        payload_json=json.dumps(payload, ensure_ascii=False),
        collection_mode=collection_mode,
        received_at=clock,
        processing_state="queued",
    )
    session.add(row)
    await session.flush()
    return row


async def commit_checkpoint_with_envelope(
    session: AsyncSession,
    *,
    source_id: int,
    dto: TelegramMessageDTO,
    collection_mode: str,
    event_type: str = "message_new",
    observed_at: datetime | None = None,
) -> TelegramEventEnvelope:
    """Persist envelope and advance checkpoint in the same transaction (D-040/COL)."""
    envelope = await persist_message_envelope(
        session,
        source_id=source_id,
        dto=dto,
        collection_mode=collection_mode,
        event_type=event_type,
        observed_at=observed_at,
    )
    checkpoint = await session.get(CollectorCheckpoint, source_id)
    if checkpoint is None:
        checkpoint = CollectorCheckpoint(source_id=source_id)
        session.add(checkpoint)
        await session.flush()
    last_id = checkpoint.last_committed_message_id or 0
    if dto.telegram_message_id >= last_id:
        checkpoint.last_committed_message_id = dto.telegram_message_id
        checkpoint.last_committed_published_at = dto.published_at
        checkpoint.version += 1
        checkpoint.updated_at = datetime.now(UTC)
    await session.flush()
    return envelope


async def handle_backfill_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    payload = json.loads(job.payload_json or "{}")
    source_id = int(payload["source_id"])
    source = await session.get(TelegramSource, source_id)
    if source is None or source.lifecycle_state != "monitoring":
        job.state = "failed"
        job.last_error_code = "source_not_monitoring"
        return {"outcome": "failed", "error": "source_not_monitoring"}

    checkpoint = await session.get(CollectorCheckpoint, source_id)
    after_id = checkpoint.last_committed_message_id if checkpoint else None
    request = HistoryRequest(
        schema_version=1,
        source_id=source_id,
        after_message_id=after_id,
        limit=int(payload.get("limit", 100)),
        purpose="backfill",
    )
    count = 0
    try:
        async for dto in gateway.iter_history(request):
            await commit_checkpoint_with_envelope(
                session,
                source_id=source_id,
                dto=dto,
                collection_mode="backfill",
                event_type="message_new",
            )
            count += 1
    except GatewayFloodWait as exc:
        job.state = "retry_wait"
        job.available_at = exc.until
        job.last_error_code = "flood_wait"
        await session.flush()
        return {"outcome": "flood_wait", "until": exc.until.isoformat(), "persisted": count}

    job.state = "succeeded"
    job.updated_at = datetime.now(UTC)
    await session.flush()
    return {"outcome": "succeeded", "persisted": count}


async def handle_reconciliation_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    payload = json.loads(job.payload_json or "{}")
    source_id = int(payload["source_id"])
    purpose = payload.get("purpose", "periodic_reconciliation")
    checkpoint = await session.get(CollectorCheckpoint, source_id)
    after_id = checkpoint.last_committed_message_id if checkpoint else None
    request = HistoryRequest(
        schema_version=1,
        source_id=source_id,
        after_message_id=after_id,
        limit=int(payload.get("limit", 100)),
        purpose=purpose,
    )
    count = 0
    try:
        async for dto in gateway.iter_history(request):
            await commit_checkpoint_with_envelope(
                session,
                source_id=source_id,
                dto=dto,
                collection_mode=purpose,
                event_type="message_new",
            )
            count += 1
    except GatewayFloodWait as exc:
        job.state = "retry_wait"
        job.available_at = exc.until
        job.last_error_code = "flood_wait"
        await session.flush()
        return {"outcome": "flood_wait", "until": exc.until.isoformat(), "persisted": count}

    if checkpoint is not None:
        checkpoint.last_reconciled_at = datetime.now(UTC)
    job.state = "succeeded"
    job.updated_at = datetime.now(UTC)
    await session.flush()
    return {"outcome": "succeeded", "persisted": count}


async def enqueue_initial_backfill(session: AsyncSession, source_id: int) -> Job:
    return await enqueue_job(
        session,
        job_type="initial_backfill",
        dedupe_key=f"initial_backfill:{source_id}",
        payload={"source_id": source_id, "limit": 100, "correlation_id": str(uuid.uuid4())},
    )
