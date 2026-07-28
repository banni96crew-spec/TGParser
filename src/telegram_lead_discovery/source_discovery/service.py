"""Source discovery: normalize, CSV import, approve → monitoring (SRC)."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import PublicSourceRef, TelegramGateway
from telegram_lead_discovery.collector.service import enqueue_initial_backfill
from telegram_lead_discovery.source_discovery.normalization import (
    USERNAME_RE as _USERNAME_RE,
)
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DiscoveryRun,
    SourceApprovalEvent,
    SourceDiscoveryEvent,
    TelegramSource,
)

USERNAME_RE = _USERNAME_RE

REJECT_REASON_CODES = frozenset(
    {"off_topic", "low_signal", "duplicate_manual", "not_needed"}
)


class SourceLifecycleError(ValueError):
    """Invalid source lifecycle transition or reason."""
    pass


@dataclass(frozen=True, slots=True)
class CsvImportRowResult:
    line_no: int
    raw: str
    ok: bool
    error_code: str | None = None
    source_id: int | None = None


async def add_manual_candidate(
    session: AsyncSession,
    *,
    username_or_url: str,
    gateway: TelegramGateway | None = None,
) -> tuple[TelegramSource, DiscoveryRun]:
    username = normalize_username(username_or_url)
    run = DiscoveryRun(
        root_source_ids_json="[]",
        max_depth=0,
        expansion_cap=0,
        candidate_cap=1,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    existing = await session.execute(
        select(TelegramSource).where(TelegramSource.username_normalized == username)
    )
    source = existing.scalar_one_or_none()
    if source is None:
        title = username
        telegram_id = None
        source_type = "channel"
        public_url = f"https://t.me/{username}"
        if gateway is not None:
            # Do not hold a write transaction across Telegram resolve.
            await session.commit()
            snap = await gateway.resolve_public_source(
                PublicSourceRef(schema_version=1, username_or_url=username)
            )
            telegram_id = snap.telegram_id
            title = snap.title
            source_type = snap.source_type
            public_url = snap.public_url
        source = TelegramSource(
            telegram_id=telegram_id,
            username_normalized=username,
            title=title,
            source_type=source_type,
            public_url=public_url,
            lifecycle_state="candidate",
            quality_score=2,
        )
        session.add(source)
        await session.flush()

    run.root_source_ids_json = f"[{source.id}]"
    session.add(
        SourceDiscoveryEvent(
            event_id=str(uuid.uuid4()),
            run_id=run.id,
            source_id=source.id,
            method="manual",
            parent_source_id=None,
            raw_reference=username_or_url,
            normalized_reference=username,
            outcome="candidate",
            depth=0,
        )
    )
    run.state = "succeeded"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return source, run


async def import_csv(
    session: AsyncSession,
    *,
    csv_text: str,
    gateway: TelegramGateway | None = None,
) -> tuple[DiscoveryRun, list[CsvImportRowResult]]:
    raw_bytes = csv_text.encode("utf-8")
    if len(raw_bytes) > 1024 * 1024:
        raise ValueError("csv_too_large")
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or "source_ref" not in reader.fieldnames:
        raise ValueError("csv_missing_source_ref")

    run = DiscoveryRun(
        root_source_ids_json="[]",
        max_depth=0,
        state="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    results: list[CsvImportRowResult] = []
    root_ids: list[int] = []
    for line_no, row in enumerate(reader, start=2):
        raw = (row.get("source_ref") or "").strip()
        if not raw:
            continue
        if line_no - 1 > 1000:
            results.append(
                CsvImportRowResult(line_no=line_no, raw=raw, ok=False, error_code="row_cap")
            )
            break
        try:
            source, _ = await add_manual_candidate(
                session, username_or_url=raw, gateway=gateway
            )
            # Re-link discovery event to this CSV run
            session.add(
                SourceDiscoveryEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=run.id,
                    source_id=source.id,
                    method="seed_import",
                    parent_source_id=None,
                    raw_reference=raw,
                    normalized_reference=source.username_normalized or "",
                    outcome="candidate",
                    depth=0,
                )
            )
            root_ids.append(source.id)
            results.append(
                CsvImportRowResult(
                    line_no=line_no, raw=raw, ok=True, source_id=source.id
                )
            )
        except InvalidUsernameError:
            results.append(
                CsvImportRowResult(
                    line_no=line_no, raw=raw, ok=False, error_code="invalid_username"
                )
            )
    run.root_source_ids_json = str(root_ids)
    run.state = "succeeded"
    run.finished_at = datetime.now(UTC)
    await session.flush()
    return run, results


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


async def list_sources(session: AsyncSession) -> list[TelegramSource]:
    result = await session.execute(select(TelegramSource).order_by(TelegramSource.id.asc()))
    return list(result.scalars().all())
