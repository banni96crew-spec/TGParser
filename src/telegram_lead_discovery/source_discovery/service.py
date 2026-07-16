"""Source discovery: normalize, CSV import, approve → monitoring (SRC)."""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import PublicSourceRef, TelegramGateway
from telegram_lead_discovery.collector.service import enqueue_initial_backfill
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DiscoveryRun,
    SourceApprovalEvent,
    SourceDiscoveryEvent,
    TelegramSource,
)

USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")


class InvalidUsernameError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CsvImportRowResult:
    line_no: int
    raw: str
    ok: bool
    error_code: str | None = None
    source_id: int | None = None


def normalize_username(value: str) -> str:
    text = value.strip()
    lower = text.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            lower = text.lower()
            break
    text = text.lstrip("@")
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    text = text.lower()
    if not USERNAME_RE.fullmatch(text):
        raise InvalidUsernameError(f"invalid_username:{value!r}")
    return text


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
    source.lifecycle_state = "approved"
    source.approved_at = datetime.now(UTC)
    await session.flush()

    ref: PublicSourceRef | int
    if source.telegram_id is not None:
        ref = source.telegram_id
    else:
        ref = PublicSourceRef(
            schema_version=1,
            username_or_url=source.username_normalized or "",
        )
    snap = await gateway.validate_source(ref)
    source.telegram_id = snap.telegram_id
    source.username_normalized = snap.username.lower()
    source.title = snap.title
    source.source_type = snap.source_type
    source.public_url = snap.public_url
    source.lifecycle_state = "monitoring"
    source.monitoring_started_at = datetime.now(UTC)
    source.access_error_code = None
    await session.flush()

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


async def list_sources(session: AsyncSession) -> list[TelegramSource]:
    result = await session.execute(select(TelegramSource).order_by(TelegramSource.id.asc()))
    return list(result.scalars().all())
