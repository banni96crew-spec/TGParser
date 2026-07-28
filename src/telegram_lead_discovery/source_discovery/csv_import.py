"""CSV source import orchestration."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import TelegramGateway
from telegram_lead_discovery.source_discovery.normalization import InvalidUsernameError
from telegram_lead_discovery.source_discovery.source_candidates import add_manual_candidate
from telegram_lead_discovery.storage.models import DiscoveryRun, SourceDiscoveryEvent


@dataclass(frozen=True, slots=True)
class CsvImportRowResult:
    line_no: int
    raw: str
    ok: bool
    error_code: str | None = None
    source_id: int | None = None


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
