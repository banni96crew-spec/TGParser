"""Collector service: envelopes, checkpoints, backfill/live (COL-005..026 / D-064)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayTransientError,
    HistoryRequest,
    TelegramGateway,
    TelegramMessageDTO,
    TelegramPeerRef,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    TelegramEventEnvelope,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import run_write

logger = logging.getLogger(__name__)

PERSIST_BATCH_SIZE = 50
HISTORY_PAGE_LIMIT = 100
BACKFILL_MAX_MESSAGES = 3000
BACKFILL_WINDOW_DAYS = 14
STARTUP_RECONCILE_BATCH = 5000
PERIODIC_RECONCILE_BATCH = 1000
TRANSIENT_RETRY_OFFSETS_SEC = (1, 5, 30, 120, 600)

WriteFn = Callable[[Callable[[AsyncSession], Awaitable[Any]]], Awaitable[Any]]


def peer_from_source(source: TelegramSource) -> TelegramPeerRef:
    """Build TelegramPeerRef from registry row — never pass DB source_id as entity."""
    return TelegramPeerRef(
        schema_version=1,
        telegram_peer_id=source.telegram_id,
        access_hash=None,
        username_normalized=source.username_normalized,
    )


def _event_id(
    source_id: int,
    event_type: str,
    message_id: int,
    edit_key: str,
) -> str:
    return f"{source_id}:{event_type}:{message_id}:{edit_key}"


def _edit_key(event_type: str, dto: TelegramMessageDTO, observed_at: datetime) -> str:
    if event_type == "message_edited" and dto.edited_at is not None:
        return dto.edited_at.isoformat()
    if event_type == "message_deleted":
        # COL-014: delete uses received_at rounded to 1s.
        return observed_at.replace(microsecond=0).isoformat()
    return "0"


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
    edit_key = _edit_key(event_type, dto, clock)
    event_id = _event_id(source_id, event_type, dto.telegram_message_id, edit_key)
    existing = await session.execute(
        select(TelegramEventEnvelope).where(TelegramEventEnvelope.event_id == event_id)
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row
    peer_id = dto.telegram_peer_id
    payload = {
        "text": dto.text,
        "published_at": dto.published_at.isoformat(),
        "edited_at": dto.edited_at.isoformat() if dto.edited_at else None,
        "author_peer_id": dto.author_peer_id,
        "author_username": dto.author_username,
        "permalink": dto.permalink,
        "telegram_peer_id": peer_id,
        "is_deleted": dto.is_deleted,
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
    if event_type != "message_deleted":
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


async def persist_envelope_batch(
    session: AsyncSession,
    *,
    source_id: int,
    messages: Sequence[TelegramMessageDTO],
    collection_mode: str,
    event_type: str = "message_new",
) -> int:
    """Persist ≤ PERSIST_BATCH_SIZE envelopes + checkpoint in one short write TX."""
    if len(messages) > PERSIST_BATCH_SIZE:
        raise ValueError(
            f"persist batch size {len(messages)} exceeds cap {PERSIST_BATCH_SIZE}"
        )
    count = 0
    for dto in messages:
        await commit_checkpoint_with_envelope(
            session,
            source_id=source_id,
            dto=dto,
            collection_mode=collection_mode,
            event_type=event_type,
        )
        count += 1
    return count


def _chunked(
    items: Sequence[TelegramMessageDTO], size: int
) -> list[list[TelegramMessageDTO]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


@dataclass(frozen=True, slots=True)
class _BackfillPrep:
    job_id: int
    source_id: int
    peer: TelegramPeerRef
    after_message_id: int | None
    continuation_cursor: str | None
    cumulative_count: int
    job_started_at: datetime
    purpose: str
    limit: int
    cancel_requested: bool
    lifecycle_state: str


async def _prepare_backfill(session: AsyncSession, job_id: int) -> _BackfillPrep | dict[str, Any]:
    job = await session.get(Job, job_id)
    if job is None:
        return {"outcome": "failed", "error": "job_not_found"}
    if job.cancel_requested_at is not None:
        job.state = "cancelled"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {"outcome": "cancelled", "persisted": 0}

    payload = json.loads(job.payload_json or "{}")
    source_id = int(payload["source_id"])
    source = await session.get(TelegramSource, source_id)
    if source is None or source.lifecycle_state != "monitoring":
        job.state = "failed"
        job.last_error_code = "source_not_monitoring"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {"outcome": "failed", "error": "source_not_monitoring"}

    try:
        peer = peer_from_source(source)
    except ValueError:
        job.state = "failed"
        job.last_error_code = "missing_peer_ref"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {"outcome": "failed", "error": "missing_peer_ref"}

    checkpoint = await session.get(CollectorCheckpoint, source_id)
    started_raw = payload.get("job_started_at")
    if started_raw:
        job_started_at = datetime.fromisoformat(started_raw)
        if job_started_at.tzinfo is None:
            job_started_at = job_started_at.replace(tzinfo=UTC)
    else:
        created = job.created_at
        job_started_at = (
            created.replace(tzinfo=UTC) if created.tzinfo is None else created
        )
        payload["job_started_at"] = job_started_at.isoformat()
        job.payload_json = json.dumps(payload, ensure_ascii=False)

    job.state = "running"
    job.updated_at = datetime.now(UTC)
    await session.flush()

    purpose = payload.get("purpose", "backfill")
    if job.job_type == "continuation":
        purpose = "continuation"
    elif job.job_type == "startup_reconciliation":
        purpose = "startup_reconciliation"
    elif job.job_type == "periodic_reconciliation":
        purpose = "periodic_reconciliation"

    # Reconciliation catches up forward from checkpoint. Initial backfill / continuation
    # walks newest→oldest via continuation_cursor — do not use checkpoint as min_id.
    after_id: int | None = None
    if purpose in {"startup_reconciliation", "periodic_reconciliation"}:
        after_id = checkpoint.last_committed_message_id if checkpoint else None

    default_limit = HISTORY_PAGE_LIMIT
    if purpose == "startup_reconciliation":
        default_limit = STARTUP_RECONCILE_BATCH
    elif purpose == "periodic_reconciliation":
        default_limit = PERIODIC_RECONCILE_BATCH

    return _BackfillPrep(
        job_id=job.id,
        source_id=source_id,
        peer=peer,
        after_message_id=after_id,
        continuation_cursor=payload.get("continuation_cursor"),
        cumulative_count=int(payload.get("cumulative_count", 0)),
        job_started_at=job_started_at,
        purpose=purpose,
        limit=int(payload.get("limit", default_limit)),
        cancel_requested=False,
        lifecycle_state=source.lifecycle_state,
    )


async def fetch_history_page(
    gateway: TelegramGateway,
    request: HistoryRequest,
) -> list[TelegramMessageDTO]:
    """Network I/O only — MUST NOT be called inside a long write transaction."""
    items: list[TelegramMessageDTO] = []
    async for dto in gateway.iter_history(request):
        items.append(dto)
    return items


async def _persist_pages(
    *,
    source_id: int,
    messages: Sequence[TelegramMessageDTO],
    collection_mode: str,
    write: WriteFn,
) -> int:
    total = 0
    for batch in _chunked(list(messages), PERSIST_BATCH_SIZE):

        async def _write_batch(
            session: AsyncSession, _batch: list[TelegramMessageDTO] = batch
        ) -> int:
            return await persist_envelope_batch(
                session,
                source_id=source_id,
                messages=_batch,
                collection_mode=collection_mode,
            )

        total += int(await write(_write_batch))
    return total


async def execute_backfill_job(
    *,
    job_id: int,
    gateway: TelegramGateway,
    write: WriteFn | None = None,
) -> dict[str, Any]:
    """Backfill/reconciliation with network outside long write TX (COL-025)."""
    write_fn: WriteFn = write or run_write
    prep = await write_fn(lambda s: _prepare_backfill(s, job_id))
    if isinstance(prep, dict):
        return prep

    window_start = prep.job_started_at - timedelta(days=BACKFILL_WINDOW_DAYS)
    request = HistoryRequest(
        schema_version=1,
        source_id=prep.source_id,
        peer=prep.peer,
        after_message_id=prep.after_message_id,
        before_published_at=None,
        limit=min(prep.limit, HISTORY_PAGE_LIMIT)
        if prep.purpose in {"backfill", "continuation"}
        else prep.limit,
        purpose=prep.purpose,  # type: ignore[arg-type]
        continuation_cursor=prep.continuation_cursor,
    )

    try:
        raw_page = await fetch_history_page(gateway, request)
    except GatewayFloodWait as flood_exc:
        until = flood_exc.until
        return await write_fn(
            lambda s: _mark_flood_wait(s, prep.job_id, until, persisted=0)
        )
    except GatewayTransientError as transient_exc:
        detail = str(transient_exc)
        return await write_fn(
            lambda s: _mark_transient(s, prep.job_id, detail)
        )

    # Telethon/fake may return newest-first; persist oldest-to-newest (COL-009).
    page = sorted(
        raw_page,
        key=lambda m: (m.published_at, m.telegram_message_id),
    )

    accepted: list[TelegramMessageDTO] = []
    hit_window = False
    for dto in page:
        if dto.published_at < window_start and prep.purpose in {
            "backfill",
            "continuation",
        }:
            hit_window = True
            break
        if prep.cumulative_count + len(accepted) >= BACKFILL_MAX_MESSAGES and prep.purpose in {
            "backfill",
            "continuation",
        }:
            break
        # Ensure peer identity is stamped for COL-026.
        if dto.telegram_peer_id is None and prep.peer.telegram_peer_id is not None:
            dto = TelegramMessageDTO(
                schema_version=dto.schema_version,
                source_id=prep.source_id,
                telegram_message_id=dto.telegram_message_id,
                published_at=dto.published_at,
                text=dto.text,
                telegram_peer_id=prep.peer.telegram_peer_id,
                edited_at=dto.edited_at,
                author_peer_id=dto.author_peer_id,
                author_username=dto.author_username,
                author_display_name=dto.author_display_name,
                permalink=dto.permalink,
                is_deleted=dto.is_deleted,
            )
        elif dto.source_id != prep.source_id:
            dto = TelegramMessageDTO(
                schema_version=dto.schema_version,
                source_id=prep.source_id,
                telegram_message_id=dto.telegram_message_id,
                published_at=dto.published_at,
                text=dto.text,
                telegram_peer_id=dto.telegram_peer_id or prep.peer.telegram_peer_id,
                edited_at=dto.edited_at,
                author_peer_id=dto.author_peer_id,
                author_username=dto.author_username,
                author_display_name=dto.author_display_name,
                permalink=dto.permalink,
                is_deleted=dto.is_deleted,
            )
        accepted.append(dto)

    collection_mode = (
        "backfill"
        if prep.purpose in {"backfill", "continuation"}
        else prep.purpose
    )
    persisted = await _persist_pages(
        source_id=prep.source_id,
        messages=accepted,
        collection_mode=collection_mode,
        write=write_fn,
    )
    new_cumulative = prep.cumulative_count + persisted

    page_full = len(raw_page) >= request.limit and len(raw_page) > 0
    under_goal = new_cumulative < BACKFILL_MAX_MESSAGES
    need_continuation = (
        prep.purpose in {"backfill", "continuation"}
        and page_full
        and under_goal
        and not hit_window
        and accepted
    )

    oldest_id = accepted[0].telegram_message_id if accepted else None
    # Next page goes older than the oldest accepted (Telethon offset_id semantics).
    next_cursor = str(oldest_id) if need_continuation and oldest_id is not None else None

    return await write_fn(
        lambda s: _finalize_backfill(
            s,
            job_id=prep.job_id,
            source_id=prep.source_id,
            persisted=persisted,
            cumulative=new_cumulative,
            need_continuation=need_continuation,
            continuation_cursor=next_cursor,
            job_started_at=prep.job_started_at,
            purpose=prep.purpose,
        )
    )


async def _mark_flood_wait(
    session: AsyncSession,
    job_id: int,
    until: datetime,
    *,
    persisted: int,
) -> dict[str, Any]:
    job = await session.get(Job, job_id)
    if job is None:
        return {"outcome": "failed", "error": "job_not_found"}
    # COL-017: attempt must not increase on FloodWait — claim already bumped;
    # compensate by decrementing so net attempt is unchanged across flood waits.
    if job.attempt > 0:
        job.attempt -= 1
    job.state = "retry_wait"
    job.available_at = until
    job.last_error_code = "flood_wait"
    job.updated_at = datetime.now(UTC)
    await session.flush()
    return {
        "outcome": "flood_wait",
        "until": until.isoformat(),
        "persisted": persisted,
        "health_reason": "flood_wait",
    }


async def _mark_transient(
    session: AsyncSession, job_id: int, detail: str
) -> dict[str, Any]:
    job = await session.get(Job, job_id)
    if job is None:
        return {"outcome": "failed", "error": "job_not_found"}
    attempt = job.attempt
    if attempt >= len(TRANSIENT_RETRY_OFFSETS_SEC):
        job.state = "dead"
        job.last_error_code = "transient_exhausted"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {
            "outcome": "dead",
            "error": detail,
            "health_reason": "transient_exhausted",
        }
    delay = TRANSIENT_RETRY_OFFSETS_SEC[attempt - 1 if attempt > 0 else 0]
    job.state = "retry_wait"
    job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
    job.last_error_code = "transient_error"
    job.updated_at = datetime.now(UTC)
    await session.flush()
    return {
        "outcome": "retry_wait",
        "error": detail,
        "health_reason": "transient_error",
        "available_at": job.available_at.isoformat(),
    }


async def _finalize_backfill(
    session: AsyncSession,
    *,
    job_id: int,
    source_id: int,
    persisted: int,
    cumulative: int,
    need_continuation: bool,
    continuation_cursor: str | None,
    job_started_at: datetime,
    purpose: str,
) -> dict[str, Any]:
    job = await session.get(Job, job_id)
    if job is None:
        return {"outcome": "failed", "error": "job_not_found"}

    if job.cancel_requested_at is not None:
        job.state = "cancelled"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {"outcome": "cancelled", "persisted": persisted}

    source = await session.get(TelegramSource, source_id)
    if source is None or source.lifecycle_state != "monitoring":
        job.state = "cancelled"
        job.last_error_code = "source_not_monitoring"
        job.updated_at = datetime.now(UTC)
        await session.flush()
        return {"outcome": "cancelled", "persisted": persisted, "reason": "paused_or_disabled"}

    payload = json.loads(job.payload_json or "{}")
    payload["cumulative_count"] = cumulative
    payload["job_started_at"] = job_started_at.isoformat()

    if need_continuation and continuation_cursor is not None:
        payload["continuation_cursor"] = continuation_cursor
        job.payload_json = json.dumps(payload, ensure_ascii=False)
        job.state = "succeeded"
        job.updated_at = datetime.now(UTC)
        cont_payload = {
            "source_id": source_id,
            "purpose": "continuation",
            "continuation_cursor": continuation_cursor,
            "cumulative_count": cumulative,
            "job_started_at": job_started_at.isoformat(),
            "limit": HISTORY_PAGE_LIMIT,
            "correlation_id": payload.get("correlation_id", str(uuid.uuid4())),
        }
        await enqueue_job(
            session,
            job_type="continuation",
            dedupe_key=f"continuation:{source_id}:{continuation_cursor}",
            payload=cont_payload,
        )
        await session.flush()
        return {
            "outcome": "continued",
            "persisted": persisted,
            "cumulative": cumulative,
            "continuation_cursor": continuation_cursor,
        }

    job.payload_json = json.dumps(payload, ensure_ascii=False)
    job.state = "succeeded"
    job.updated_at = datetime.now(UTC)
    if purpose in {"startup_reconciliation", "periodic_reconciliation"}:
        checkpoint = await session.get(CollectorCheckpoint, source_id)
        if checkpoint is not None:
            checkpoint.last_reconciled_at = datetime.now(UTC)
    await session.flush()
    return {"outcome": "succeeded", "persisted": persisted, "cumulative": cumulative}


async def handle_backfill_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    """Compatibility wrapper for callers that already hold the write lock.

    Commits the open transaction, then runs ``execute_backfill_job`` with a
    nested session writer that does **not** re-acquire ``run_write``'s lock
    (would deadlock). Prefer calling ``execute_backfill_job`` directly.
    """
    from telegram_lead_discovery.storage import db as storage_db

    job_id = job.id
    await session.commit()

    async def _nested_write(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async with storage_db.session_scope() as nested:
            return await fn(nested)

    return await execute_backfill_job(
        job_id=job_id, gateway=gateway, write=_nested_write
    )


async def handle_reconciliation_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    return await handle_backfill_job(session, job, gateway)


async def enqueue_initial_backfill(session: AsyncSession, source_id: int) -> Job:
    return await enqueue_job(
        session,
        job_type="initial_backfill",
        dedupe_key=f"initial_backfill:{source_id}",
        payload={
            "source_id": source_id,
            "limit": HISTORY_PAGE_LIMIT,
            "purpose": "backfill",
            "cumulative_count": 0,
            "job_started_at": datetime.now(UTC).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        },
    )


async def cancel_collector_jobs_for_source(
    session: AsyncSession, source_id: int
) -> int:
    """COL-011: cancel queued jobs; mark running with cancel_requested_at."""
    now = datetime.now(UTC)
    result = await session.execute(
        select(Job).where(
            Job.state.in_(("queued", "retry_wait", "running")),
        )
    )
    cancelled = 0
    for job in result.scalars():
        payload = json.loads(job.payload_json or "{}")
        if int(payload.get("source_id", -1)) != source_id:
            continue
        if job.state == "running":
            job.cancel_requested_at = now
        else:
            job.state = "cancelled"
        job.updated_at = now
        cancelled += 1
    await session.flush()
    return cancelled


async def load_monitoring_peer_map(
    session: AsyncSession,
) -> dict[int, int]:
    """Map telegram_peer_id → DB source_id for monitoring sources only."""
    result = await session.execute(
        select(TelegramSource).where(TelegramSource.lifecycle_state == "monitoring")
    )
    mapping: dict[int, int] = {}
    for src in result.scalars():
        if src.telegram_id is not None:
            mapping[src.telegram_id] = src.id
    return mapping


async def ingest_live_update(
    session: AsyncSession,
    update: TelegramUpdateDTO,
    *,
    monitoring_map: dict[int, int] | None = None,
) -> TelegramEventEnvelope | None:
    """Persist one live update if peer maps to a monitoring source (COL-006/026)."""
    peer_id = update.telegram_peer_id
    if peer_id is None and update.message is not None:
        peer_id = update.message.telegram_peer_id
    if peer_id is None:
        return None

    if monitoring_map is None:
        monitoring_map = await load_monitoring_peer_map(session)
    source_id = monitoring_map.get(peer_id)
    if source_id is None:
        return None

    source = await session.get(TelegramSource, source_id)
    if source is None or source.lifecycle_state != "monitoring":
        return None

    dto = update.message
    if dto is None:
        return None

    stamped = TelegramMessageDTO(
        schema_version=dto.schema_version,
        source_id=source_id,
        telegram_message_id=dto.telegram_message_id,
        published_at=dto.published_at,
        text=dto.text,
        telegram_peer_id=peer_id,
        edited_at=dto.edited_at,
        author_peer_id=dto.author_peer_id,
        author_username=dto.author_username,
        author_display_name=dto.author_display_name,
        permalink=dto.permalink,
        is_deleted=dto.is_deleted or update.event_type == "message_deleted",
    )
    return await commit_checkpoint_with_envelope(
        session,
        source_id=source_id,
        dto=stamped,
        collection_mode="live",
        event_type=update.event_type,
        observed_at=update.observed_at,
    )


async def consume_live_updates(
    gateway: TelegramGateway,
    *,
    write: WriteFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Consume ``iter_updates``; filter monitoring; short persist TX per update.

    Pause/disable takes effect without process restart: each update reloads
    the monitoring map (or checks lifecycle) before persist.
    """
    write_fn: WriteFn = write or run_write
    accepted = 0
    discarded = 0
    try:
        async for update in gateway.iter_updates():
            if should_stop is not None and should_stop():
                break

            current = update

            async def _ingest(
                session: AsyncSession, _update: TelegramUpdateDTO = current
            ) -> TelegramEventEnvelope | None:
                return await ingest_live_update(session, _update)

            try:
                row = await write_fn(_ingest)
            except Exception:  # noqa: BLE001
                logger.exception("live_ingest_failed")
                raise
            if row is None:
                discarded += 1
            else:
                accepted += 1
    except GatewayFloodWait as exc:
        return {
            "accepted": accepted,
            "discarded": discarded,
            "health_reason": "flood_wait",
            "flood_wait_until": exc.until.isoformat(),  # type: ignore[dict-item]
        }
    return {"accepted": accepted, "discarded": discarded}


async def request_source_pause_ingest(
    session: AsyncSession, source_id: int
) -> None:
    """Operator pause helper: set paused + cancel collector jobs (COL-011)."""
    source = await session.get(TelegramSource, source_id)
    if source is None:
        raise KeyError(source_id)
    source.lifecycle_state = "paused"
    source.updated_at = datetime.now(UTC)
    await cancel_collector_jobs_for_source(session, source_id)
    await session.flush()


COLLECTOR_JOB_TYPES = (
    "initial_backfill",
    "continuation",
    "startup_reconciliation",
    "periodic_reconciliation",
)


async def claim_and_process_collector_job(
    gateway: TelegramGateway,
    *,
    owner: str = "collector-job-worker",
    write: WriteFn | None = None,
) -> dict[str, Any] | None:
    """Claim one collector backfill/reconcile job and execute it (INF-022)."""
    from telegram_lead_discovery.storage.jobs import claim_job

    write_fn: WriteFn = write or run_write

    async def _claim(session: AsyncSession) -> int | None:
        job = await claim_job(
            session,
            job_types=list(COLLECTOR_JOB_TYPES),
            owner=owner,
        )
        return None if job is None else job.id

    job_id = await write_fn(_claim)
    if job_id is None:
        return None
    return await execute_backfill_job(job_id=job_id, gateway=gateway, write=write_fn)


async def enqueue_startup_reconciliation(
    session: AsyncSession,
    *,
    startup_token: str,
) -> int:
    """Enqueue one startup reconciliation job per monitoring source (D-019/D-066)."""
    result = await session.execute(
        select(TelegramSource).where(TelegramSource.lifecycle_state == "monitoring")
    )
    count = 0
    now = datetime.now(UTC)
    for src in result.scalars():
        await enqueue_job(
            session,
            job_type="startup_reconciliation",
            dedupe_key=f"startup_reconciliation:{src.id}:{startup_token}",
            payload={
                "source_id": src.id,
                "purpose": "startup_reconciliation",
                "limit": STARTUP_RECONCILE_BATCH,
                "cumulative_count": 0,
                "job_started_at": now.isoformat(),
                "correlation_id": str(uuid.uuid4()),
            },
        )
        count += 1
    return count


def _periodic_bucket(now: datetime) -> str:
    """Floor UTC time to 15-minute bucket for periodic dedupe keys."""
    floored = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return floored.strftime("%Y%m%dT%H%M")


async def enqueue_periodic_reconciliation(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Enqueue periodic reconciliation jobs (every 15 minutes, D-019/INF-022)."""
    clock = now or datetime.now(UTC)
    bucket = _periodic_bucket(clock)
    result = await session.execute(
        select(TelegramSource).where(TelegramSource.lifecycle_state == "monitoring")
    )
    count = 0
    for src in result.scalars():
        await enqueue_job(
            session,
            job_type="periodic_reconciliation",
            dedupe_key=f"periodic_reconciliation:{src.id}:{bucket}",
            payload={
                "source_id": src.id,
                "purpose": "periodic_reconciliation",
                "limit": PERIODIC_RECONCILE_BATCH,
                "cumulative_count": 0,
                "job_started_at": clock.isoformat(),
                "correlation_id": str(uuid.uuid4()),
            },
        )
        count += 1
    return count
