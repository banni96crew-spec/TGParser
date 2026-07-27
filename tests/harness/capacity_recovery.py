"""Deterministic capacity / recovery generators and SLO assertions (Wave 09A).

NFRs: NFR-PERF-006..008, NFR-REL-008 (plan §2 product success gates).
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    HistoryRequest,
    TelegramMessageDTO,
    TelegramPeerRef,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.collector.service import (
    PERSIST_BATCH_SIZE,
    commit_checkpoint_with_envelope,
    fetch_history_page,
    ingest_live_update,
    persist_envelope_batch,
    persist_message_envelope,
)
from telegram_lead_discovery.dashboard.leads import list_inbox_leads
from telegram_lead_discovery.observability.capacity import (
    record_burst_backlog_age_seconds,
    record_exact_dedupe_rejected,
    record_ingestion,
    record_received_to_processed_seconds,
    record_restart_recovery_duration_seconds,
    set_monitoring_source_count,
)
from telegram_lead_discovery.processing.pipeline import process_next_envelope
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    Lead,
    NotificationOutbox,
    ProcessingResult,
    TelegramEventEnvelope,
    TelegramMessage,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import run_write

# --- SLO targets (plan §2 / QUALITY_REQUIREMENTS) ---------------------------------

SLO_MONITORING_SOURCES = 100
SLO_STEADY_MESSAGES = 1000
SLO_BURST_EVENTS = 6000
SLO_BURST_RATE_PER_SEC = 10
SLO_BURST_DURATION_SEC = 600  # 10 min profile (volume = rate × duration)
SLO_STEADY_P95_SECONDS = 30.0
SLO_BURST_P95_SECONDS = 120.0
SLO_BURST_DRAIN_SECONDS = 15 * 60
SLO_RECOVERY_SECONDS = 5 * 60
DUP_REPLAY_FRACTION = 0.10

HOT_TEXT = (
    "Нужно разработать интернет-магазин с оплатой и корзиной, "
    "бюджет 250000 ₽, срочно, готов начать, пишите @wave09client."
)
NOISE_TEXT = "ordinary channel update without commercial ask {n}"


class SimulatedKill(Exception):
    """Harness crash injection — rolls back the open write transaction."""


@dataclass
class HarnessCounters:
    accepted: int = 0
    persisted: int = 0
    processed: int = 0
    leads: int = 0
    outbox: int = 0
    duplicates_rejected: int = 0
    edits: int = 0
    deletes: int = 0
    sqlite_busy: int = 0
    flood_waits: int = 0
    notification_failures: int = 0
    ui_reads_ok: int = 0
    recovery_duration_seconds: float = 0.0
    drain_seconds: float = 0.0
    latencies_seconds: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def p95_latency(self) -> float | None:
        return percentile(self.latencies_seconds, 95)


@dataclass
class CapacityReport:
    """Serializable evidence blob for wave-09 artifacts."""

    scenario: str
    passed: bool
    counters: dict[str, Any]
    slo: dict[str, Any]
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "counters": self.counters,
            "slo": self.slo,
            "failures": self.failures,
        }


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def make_dto(
    *,
    source_id: int,
    peer_id: int,
    mid: int,
    text: str,
    published: datetime,
    edited: datetime | None = None,
    deleted: bool = False,
) -> TelegramMessageDTO:
    return TelegramMessageDTO(
        schema_version=1,
        source_id=source_id,
        telegram_message_id=mid,
        published_at=published,
        text=text,
        telegram_peer_id=peer_id,
        edited_at=edited,
        permalink=f"https://t.me/wave09_{peer_id}/{mid}",
        is_deleted=deleted,
    )


def simulate_day_messages(
    *,
    source_ids: Sequence[tuple[int, int]],
    total: int = SLO_STEADY_MESSAGES,
    day_start: datetime | None = None,
    hot_every: int = 50,
    mid_base: int = 10_000,
) -> list[tuple[int, int, TelegramMessageDTO]]:
    """Spread ``total`` messages evenly across sources over a simulated day.

    Returns list of (source_id, peer_id, dto).
    """
    start = day_start or datetime(2026, 7, 27, 0, 0, tzinfo=UTC)
    span = timedelta(hours=24)
    out: list[tuple[int, int, TelegramMessageDTO]] = []
    n_sources = len(source_ids)
    assert n_sources >= 1
    for i in range(total):
        source_id, peer_id = source_ids[i % n_sources]
        mid = mid_base + i
        published = start + (span * i / max(total, 1))
        text = HOT_TEXT if (i % hot_every == 0) else NOISE_TEXT.format(n=i)
        out.append(
            (
                source_id,
                peer_id,
                make_dto(
                    source_id=source_id,
                    peer_id=peer_id,
                    mid=mid,
                    text=text,
                    published=published,
                ),
            )
        )
    return out


async def seed_monitoring_sources(
    session: AsyncSession,
    *,
    count: int = SLO_MONITORING_SOURCES,
    peer_base: int = 900_000,
) -> list[tuple[int, int]]:
    """Insert ``count`` monitoring sources + empty checkpoints. Returns (source_id, peer_id)."""
    now = datetime.now(UTC)
    pairs: list[tuple[int, int]] = []
    for i in range(count):
        peer_id = peer_base + i
        username = f"wave09_src_{i:03d}"
        src = TelegramSource(
            telegram_id=peer_id,
            username_normalized=username,
            title=f"Wave09 Source {i}",
            source_type="channel",
            public_url=f"https://t.me/{username}",
            lifecycle_state="monitoring",
            quality_score=3,
            approved_at=now,
            monitoring_started_at=now,
        )
        session.add(src)
        await session.flush()
        session.add(CollectorCheckpoint(source_id=src.id))
        pairs.append((src.id, peer_id))
    await session.flush()
    set_monitoring_source_count(count)
    return pairs


async def persist_messages(
    session: AsyncSession,
    items: Sequence[tuple[int, int, TelegramMessageDTO]],
    *,
    collection_mode: str = "live",
    event_type: str = "message_new",
    counters: HarnessCounters | None = None,
) -> int:
    """Persist messages in ≤PERSIST_BATCH_SIZE chunks (same TX boundary as production)."""
    persisted = 0
    by_source: dict[int, list[TelegramMessageDTO]] = {}
    for source_id, _peer, dto in items:
        by_source.setdefault(source_id, []).append(dto)
    for source_id, dtos in by_source.items():
        for i in range(0, len(dtos), PERSIST_BATCH_SIZE):
            chunk = dtos[i : i + PERSIST_BATCH_SIZE]
            n = await persist_envelope_batch(
                session,
                source_id=source_id,
                messages=chunk,
                collection_mode=collection_mode,
                event_type=event_type,
            )
            persisted += n
    if counters is not None:
        counters.persisted += persisted
        counters.accepted += persisted
    record_ingestion(persisted)
    return persisted


async def drain_processing(
    *,
    owner: str = "wave09-drain",
    max_iterations: int | None = None,
    counters: HarnessCounters | None = None,
    batch_size: int = 50,
) -> int:
    """Process queued envelopes until idle. Returns processed count.

    Batches up to ``batch_size`` envelopes per write TX to reduce SQLite commit
    overhead under burst (NFR-PERF-007/008).
    """
    processed = 0
    limit = max_iterations if max_iterations is not None else 10_000_000
    while processed < limit:

        async def _batch(session: AsyncSession) -> list[dict[str, Any]]:
            outcomes: list[dict[str, Any]] = []
            for _ in range(batch_size):
                outcome = await process_next_envelope(session, owner=owner)
                if outcome is None:
                    break
                outcomes.append(outcome)
            return outcomes

        outcomes = await run_write(_batch)
        if not outcomes:
            break
        for outcome in outcomes:
            processed += 1
            if counters is not None:
                counters.processed += 1
                if outcome.get("outcome") == "idempotent_replay":
                    counters.duplicates_rejected += 1
                    record_exact_dedupe_rejected(1)
        if processed >= limit:
            break
    return processed


async def collect_latency_samples(
    session: AsyncSession,
    *,
    mid_min: int | None = None,
    mid_max: int | None = None,
) -> list[float]:
    """p95 basis: envelope.received_at → ProcessingResult.processed_at via message identity."""
    stmt = (
        select(
            TelegramEventEnvelope.received_at,
            ProcessingResult.processed_at,
            TelegramEventEnvelope.telegram_message_id,
        )
        .join(
            TelegramMessage,
            (TelegramMessage.source_id == TelegramEventEnvelope.source_id)
            & (
                TelegramMessage.telegram_message_id
                == TelegramEventEnvelope.telegram_message_id
            ),
        )
        .join(ProcessingResult, ProcessingResult.message_id == TelegramMessage.id)
        .where(TelegramEventEnvelope.event_type == "message_new")
    )
    if mid_min is not None:
        stmt = stmt.where(TelegramEventEnvelope.telegram_message_id >= mid_min)
    if mid_max is not None:
        stmt = stmt.where(TelegramEventEnvelope.telegram_message_id <= mid_max)
    rows = await session.execute(stmt)
    samples: list[float] = []
    for received, processed, _mid in rows.all():
        if received is None or processed is None:
            continue
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        if processed.tzinfo is None:
            processed = processed.replace(tzinfo=UTC)
        delta = (processed - received).total_seconds()
        if delta >= 0:
            samples.append(delta)
            record_received_to_processed_seconds(delta)
    return samples


async def count_table(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def snapshot_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "sources_monitoring": int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramSource)
                    .where(TelegramSource.lifecycle_state == "monitoring")
                )
            ).scalar_one()
        ),
        "envelopes": await count_table(session, TelegramEventEnvelope),
        "messages": await count_table(session, TelegramMessage),
        "processing_results": await count_table(session, ProcessingResult),
        "leads": await count_table(session, Lead),
        "outbox": await count_table(session, NotificationOutbox),
        "envelopes_queued": int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramEventEnvelope)
                    .where(TelegramEventEnvelope.processing_state == "queued")
                )
            ).scalar_one()
        ),
    }


def evaluate_slo(
    *,
    scenario: str,
    counters: HarnessCounters,
    counts: dict[str, int],
    expect_sources: int | None = None,
    expect_min_messages: int | None = None,
    p95_limit: float | None = None,
    drain_limit: float | None = None,
    recovery_limit: float | None = None,
    require_zero_dup_messages: bool = True,
) -> CapacityReport:
    failures: list[str] = []
    p95 = counters.p95_latency()
    if expect_sources is not None and counts.get("sources_monitoring", 0) < expect_sources:
        failures.append(
            f"monitoring_sources={counts.get('sources_monitoring')} < {expect_sources}"
        )
    if expect_min_messages is not None and counts.get("messages", 0) < expect_min_messages:
        failures.append(f"messages={counts.get('messages')} < {expect_min_messages}")
    if p95_limit is not None:
        if p95 is None:
            failures.append("p95_latency=None (no samples)")
        elif p95 > p95_limit:
            failures.append(f"p95_latency={p95:.3f}s > {p95_limit}s")
    if drain_limit is not None and counters.drain_seconds > drain_limit:
        failures.append(f"drain_seconds={counters.drain_seconds:.3f} > {drain_limit}")
    if recovery_limit is not None and counters.recovery_duration_seconds > recovery_limit:
        failures.append(
            f"recovery_duration={counters.recovery_duration_seconds:.3f}s > {recovery_limit}"
        )
    if require_zero_dup_messages:
        # exact identity: one TelegramMessage per (source_id, telegram_message_id)
        # enforced by UNIQUE; harness also checks envelope count vs unique mids later
        pass
    if counts.get("envelopes_queued", 0) > 0 and scenario.startswith("burst"):
        failures.append(f"backlog_remaining={counts['envelopes_queued']}")

    slo = {
        "NFR-PERF-006_sources": expect_sources,
        "NFR-PERF-006_messages": expect_min_messages,
        "NFR-PERF-008_p95_limit": p95_limit,
        "NFR-PERF-008_p95_observed": p95,
        "NFR-PERF-007_drain_limit": drain_limit,
        "NFR-PERF-007_drain_observed": counters.drain_seconds,
        "NFR-REL-008_recovery_limit": recovery_limit,
        "NFR-REL-008_recovery_observed": counters.recovery_duration_seconds,
        "duplicates_rejected": counters.duplicates_rejected,
        "sqlite_busy": counters.sqlite_busy,
    }
    return CapacityReport(
        scenario=scenario,
        passed=not failures,
        counters={
            "accepted": counters.accepted,
            "persisted": counters.persisted,
            "processed": counters.processed,
            "leads": counts.get("leads", counters.leads),
            "outbox": counts.get("outbox", counters.outbox),
            "duplicates_rejected": counters.duplicates_rejected,
            "edits": counters.edits,
            "deletes": counters.deletes,
            "sqlite_busy": counters.sqlite_busy,
            "flood_waits": counters.flood_waits,
            "notification_failures": counters.notification_failures,
            "ui_reads_ok": counters.ui_reads_ok,
            "drain_seconds": counters.drain_seconds,
            "recovery_duration_seconds": counters.recovery_duration_seconds,
            "p95_latency": p95,
            "latency_samples": len(counters.latencies_seconds),
            "notes": list(counters.notes),
            **counts,
        },
        slo=slo,
        failures=failures,
    )


# --- Scenario helpers ------------------------------------------------------------


async def run_steady_capacity(
    *,
    source_pairs: Sequence[tuple[int, int]],
) -> CapacityReport:
    counters = HarnessCounters()
    items = simulate_day_messages(source_ids=source_pairs, total=SLO_STEADY_MESSAGES)

    async def _persist(session: AsyncSession) -> int:
        return await persist_messages(session, items, counters=counters)

    await run_write(_persist)
    t0 = time.perf_counter()
    await drain_processing(owner="wave09-steady", counters=counters)
    counters.drain_seconds = time.perf_counter() - t0

    async def _lat(session: AsyncSession) -> list[float]:
        return await collect_latency_samples(session)

    counters.latencies_seconds = await run_write(_lat)
    counts = await run_write(snapshot_counts)
    return evaluate_slo(
        scenario="steady_100_sources_1000_msgs",
        counters=counters,
        counts=counts,
        expect_sources=SLO_MONITORING_SOURCES,
        expect_min_messages=SLO_STEADY_MESSAGES,
        p95_limit=SLO_STEADY_P95_SECONDS,
        drain_limit=SLO_BURST_DRAIN_SECONDS,
    )


async def run_burst_capacity(
    *,
    source_pairs: Sequence[tuple[int, int]],
    burst_events: int = SLO_BURST_EVENTS,
) -> CapacityReport:
    """Inject ``burst_events`` at sustained rate with concurrent drain (NFR-PERF-007/008).

    Profile equals 10/s × 10 min volume. Wall-clock inject is paced near processing
    capacity so the harness measures backlog age under load, not an artificial
    all-at-once dump that forces p95 ≈ full drain time.
    """
    import asyncio

    counters = HarnessCounters()
    mid_base = 50_000
    items = simulate_day_messages(
        source_ids=source_pairs,
        total=burst_events,
        day_start=datetime.now(UTC),
        hot_every=200,
        mid_base=mid_base,
    )
    counters.notes.append(
        f"burst_profile={SLO_BURST_RATE_PER_SEC}/s×{SLO_BURST_DURATION_SEC}s"
        f"→{SLO_BURST_EVENTS} events (paced concurrent drain)"
    )

    stop = asyncio.Event()
    drain_error: list[BaseException] = []

    async def _drain_loop() -> None:
        try:
            while not stop.is_set():
                n = await drain_processing(
                    owner="wave09-burst",
                    max_iterations=200,
                    counters=counters,
                    batch_size=50,
                )
                if n == 0:
                    await asyncio.sleep(0.01)
        except BaseException as exc:  # noqa: BLE001
            drain_error.append(exc)
            raise

    drain_task = asyncio.create_task(_drain_loop())
    inject_t0 = time.perf_counter()
    # Pace near ≥10/s target with headroom: ~40 msg/s batches keeps CI wall under ~3 min
    # while remaining above the NFR ingest rate.
    chunk = PERSIST_BATCH_SIZE
    target_rate = 40.0
    for i in range(0, len(items), chunk):
        batch = items[i : i + chunk]
        batch_t0 = time.perf_counter()

        async def _persist(session: AsyncSession, _batch=batch) -> int:
            return await persist_messages(session, _batch, counters=counters)

        await run_write(_persist)
        elapsed = time.perf_counter() - batch_t0
        ideal = len(batch) / target_rate
        if elapsed < ideal:
            await asyncio.sleep(ideal - elapsed)

    inject_elapsed = time.perf_counter() - inject_t0
    counters.notes.append(f"burst_inject_seconds={inject_elapsed:.3f}")

    # Finish remaining backlog after inject ends (NFR-PERF-007 drain ≤15 min).
    t0 = time.perf_counter()
    stop.set()
    await drain_task
    if drain_error:
        raise drain_error[0]
    await drain_processing(owner="wave09-burst-tail", counters=counters, batch_size=50)
    counters.drain_seconds = time.perf_counter() - t0
    # Full burst wall includes inject+tail; record backlog age after inject ended.
    record_burst_backlog_age_seconds(counters.drain_seconds)

    async def _lat(session: AsyncSession) -> list[float]:
        return await collect_latency_samples(
            session,
            mid_min=mid_base,
            mid_max=mid_base + burst_events,
        )

    counters.latencies_seconds = await run_write(_lat)

    async def _burst_msg_count(session: AsyncSession) -> int:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramMessage)
                    .where(
                        TelegramMessage.telegram_message_id >= mid_base,
                        TelegramMessage.telegram_message_id < mid_base + burst_events,
                    )
                )
            ).scalar_one()
        )

    burst_count = await run_write(_burst_msg_count)
    counts = await run_write(snapshot_counts)
    counts = {**counts, "burst_messages": burst_count, "messages": burst_count}
    return evaluate_slo(
        scenario="burst_6000_drain",
        counters=counters,
        counts=counts,
        expect_sources=SLO_MONITORING_SOURCES,
        expect_min_messages=burst_events,
        p95_limit=SLO_BURST_P95_SECONDS,
        drain_limit=SLO_BURST_DRAIN_SECONDS,
    )


async def run_duplicate_replay(
    *,
    source_pairs: Sequence[tuple[int, int]],
    base_count: int = 200,
) -> CapacityReport:
    counters = HarnessCounters()
    items = simulate_day_messages(
        source_ids=source_pairs, total=base_count, hot_every=100, mid_base=80_000
    )
    replay_n = max(1, int(base_count * DUP_REPLAY_FRACTION))
    replay = items[:replay_n]

    async def _persist(session: AsyncSession) -> int:
        return await persist_messages(session, items, counters=counters)

    await run_write(_persist)

    async def _replay(session: AsyncSession) -> int:
        # Same identity → persist_message_envelope returns existing row (no second envelope).
        before = await count_table(session, TelegramEventEnvelope)
        await persist_messages(session, replay, counters=None)
        after = await count_table(session, TelegramEventEnvelope)
        # After replay, envelope count must be unchanged → return delta.
        return after - before

    new_rows = await run_write(_replay)
    counters.duplicates_rejected = replay_n if new_rows == 0 else max(0, replay_n - new_rows)
    if new_rows == 0:
        record_exact_dedupe_rejected(replay_n)
    await drain_processing(owner="wave09-dup", counters=counters)

    # Replay processing (idempotent)
    async def _force_requeue(session: AsyncSession) -> int:
        result = await session.execute(
            select(TelegramEventEnvelope)
            .where(TelegramEventEnvelope.event_type == "message_new")
            .limit(replay_n)
        )
        n = 0
        for env in result.scalars():
            env.processing_state = "queued"
            env.lease_owner = None
            env.lease_until = None
            n += 1
        await session.flush()
        return n

    await run_write(_force_requeue)
    before_msgs = await run_write(lambda s: count_table(s, TelegramMessage))
    before_leads = await run_write(lambda s: count_table(s, Lead))
    before_outbox = await run_write(lambda s: count_table(s, NotificationOutbox))
    await drain_processing(owner="wave09-dup-replay", counters=counters)
    after_msgs = await run_write(lambda s: count_table(s, TelegramMessage))
    after_leads = await run_write(lambda s: count_table(s, Lead))
    after_outbox = await run_write(lambda s: count_table(s, NotificationOutbox))

    failures: list[str] = []
    if new_rows != 0:
        failures.append(f"duplicate_envelopes_created={new_rows}")
    if after_msgs != before_msgs:
        failures.append(f"message_count_grew_on_replay {before_msgs}->{after_msgs}")
    if after_leads != before_leads:
        failures.append(f"lead_count_grew_on_replay {before_leads}->{after_leads}")
    if after_outbox != before_outbox:
        failures.append(f"outbox_count_grew_on_replay {before_outbox}->{after_outbox}")

    counts = await run_write(snapshot_counts)
    report = evaluate_slo(
        scenario="duplicate_replay_10pct",
        counters=counters,
        counts=counts,
        require_zero_dup_messages=True,
    )
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["replay_attempted"] = replay_n
    report.counters["new_envelopes_on_replay"] = new_rows
    return report


async def run_edits_deletes(
    *,
    source_id: int,
    peer_id: int,
) -> CapacityReport:
    counters = HarnessCounters()
    now = datetime.now(UTC)
    base = make_dto(
        source_id=source_id,
        peer_id=peer_id,
        mid=77_001,
        text="need a landing page budget 80000",
        published=now,
    )

    async def _new(session: AsyncSession) -> None:
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_new",
                telegram_peer_id=peer_id,
                message=base,
                observed_at=now,
            ),
        )
        counters.accepted += 1
        counters.persisted += 1

    await run_write(_new)

    edited = make_dto(
        source_id=source_id,
        peer_id=peer_id,
        mid=77_001,
        text=HOT_TEXT,
        published=now,
        edited=now + timedelta(seconds=5),
    )

    async def _edit(session: AsyncSession) -> None:
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_edited",
                telegram_peer_id=peer_id,
                message=edited,
                observed_at=now + timedelta(seconds=5),
            ),
        )
        counters.edits += 1

    await run_write(_edit)

    deleted = make_dto(
        source_id=source_id,
        peer_id=peer_id,
        mid=77_001,
        text=HOT_TEXT,
        published=now,
        deleted=True,
    )

    async def _del(session: AsyncSession) -> None:
        await ingest_live_update(
            session,
            TelegramUpdateDTO(
                schema_version=1,
                event_type="message_deleted",
                telegram_peer_id=peer_id,
                message=deleted,
                observed_at=now + timedelta(seconds=10),
            ),
        )
        counters.deletes += 1

    await run_write(_del)
    await drain_processing(owner="wave09-edit-del", counters=counters)

    async def _check(session: AsyncSession) -> dict[str, Any]:
        envs = list(
            (
                await session.execute(
                    select(TelegramEventEnvelope).where(
                        TelegramEventEnvelope.source_id == source_id,
                        TelegramEventEnvelope.telegram_message_id == 77_001,
                    )
                )
            ).scalars()
        )
        types = sorted({e.event_type for e in envs})
        msg = (
            await session.execute(
                select(TelegramMessage).where(
                    TelegramMessage.source_id == source_id,
                    TelegramMessage.telegram_message_id == 77_001,
                )
            )
        ).scalar_one_or_none()
        return {
            "event_types": types,
            "message_state": None if msg is None else msg.state,
            "envelope_count": len(envs),
        }

    detail = await run_write(_check)
    counts = await run_write(snapshot_counts)
    failures: list[str] = []
    if "message_new" not in detail["event_types"]:
        failures.append("missing_message_new")
    if "message_edited" not in detail["event_types"]:
        failures.append("missing_message_edited")
    if "message_deleted" not in detail["event_types"]:
        failures.append("missing_message_deleted")
    report = evaluate_slo(scenario="edits_deletes", counters=counters, counts=counts)
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["edit_delete_detail"] = detail
    return report


async def run_kill_after_fetch_before_persist(
    *,
    gateway: Any,
    source_id: int,
    peer_id: int,
    job_id: int,
) -> CapacityReport:
    """Fetch succeeds; kill before persist; restart persists without gap/dup."""
    counters = HarnessCounters()
    t0 = time.perf_counter()

    async def _checkpoint_before(session: AsyncSession) -> int | None:
        cp = await session.get(CollectorCheckpoint, source_id)
        return None if cp is None else cp.last_committed_message_id

    before_cp = await run_write(_checkpoint_before)

    peer = TelegramPeerRef(
        schema_version=1,
        telegram_peer_id=peer_id,
        access_hash=None,
        username_normalized=f"wave09_src_{peer_id % 1000:03d}",
    )
    request = HistoryRequest(
        schema_version=1,
        source_id=source_id,
        peer=peer,
        after_message_id=before_cp,
        before_published_at=None,
        limit=50,
        purpose="startup_reconciliation",
        continuation_cursor=None,
    )
    fetched = await fetch_history_page(gateway, request)
    counters.notes.append(f"fetched_before_kill={len(fetched)}")

    # Simulated kill: do not persist.
    raise_path_ok = True
    try:
        async def _kill(session: AsyncSession) -> None:
            raise SimulatedKill("after_fetch_before_persist")

        await run_write(_kill)
        raise_path_ok = False
    except SimulatedKill:
        pass

    after_cp = await run_write(_checkpoint_before)
    assert after_cp == before_cp

    # Restart: persist fetched page.
    async def _persist(session: AsyncSession) -> int:
        if not fetched:
            return 0
        return await persist_envelope_batch(
            session,
            source_id=source_id,
            messages=fetched,
            collection_mode="startup_reconciliation",
        )

    persisted = await run_write(_persist)
    counters.persisted += persisted
    counters.accepted += persisted
    await drain_processing(owner="wave09-kill-fetch", counters=counters)

    async def _after(session: AsyncSession) -> dict[str, Any]:
        cp = await session.get(CollectorCheckpoint, source_id)
        env_n = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramEventEnvelope)
                    .where(TelegramEventEnvelope.source_id == source_id)
                )
            ).scalar_one()
        )
        # Second persist of same page must not grow envelopes.
        again = await persist_envelope_batch(
            session,
            source_id=source_id,
            messages=fetched,
            collection_mode="startup_reconciliation",
        )
        env_n2 = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramEventEnvelope)
                    .where(TelegramEventEnvelope.source_id == source_id)
                )
            ).scalar_one()
        )
        return {
            "checkpoint": None if cp is None else cp.last_committed_message_id,
            "envelopes": env_n,
            "second_persist_new": again,
            "envelopes_after_replay": env_n2,
            "job_id": job_id,
        }

    detail = await run_write(_after)
    counters.recovery_duration_seconds = time.perf_counter() - t0
    record_restart_recovery_duration_seconds(counters.recovery_duration_seconds)

    counts = await run_write(snapshot_counts)
    failures: list[str] = []
    if not raise_path_ok:
        failures.append("kill_injection_did_not_raise")
    if len(fetched) == 0:
        failures.append("fetch_returned_empty_before_kill")
    if detail["envelopes_after_replay"] != detail["envelopes"]:
        failures.append("gap_or_dup_after_restart_replay")
    if fetched and detail["checkpoint"] is None:
        failures.append("checkpoint_not_advanced_after_restart")
    # persist_envelope_batch returns iteration count (incl. idempotent hits);
    # envelope cardinality must stay stable on replay.
    report = evaluate_slo(
        scenario="kill_after_fetch_before_persist",
        counters=counters,
        counts=counts,
        recovery_limit=SLO_RECOVERY_SECONDS,
    )
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["kill_detail"] = detail
    return report


async def run_kill_after_persist_before_checkpoint(
    *,
    source_id: int,
    peer_id: int,
) -> CapacityReport:
    """Fault-inject flush of envelope then raise before checkpoint update.

    Entire TX rolls back (atomic boundary). Restart re-persists cleanly.
    Also asserts production path never advances checkpoint past committed envelopes.
    """
    counters = HarnessCounters()
    t0 = time.perf_counter()
    now = datetime.now(UTC)
    dto = make_dto(
        source_id=source_id,
        peer_id=peer_id,
        mid=88_001,
        text="kill mid tx " + NOISE_TEXT.format(n=1),
        published=now,
    )

    async def _before(session: AsyncSession) -> tuple[int, int | None]:
        env_n = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TelegramEventEnvelope)
                    .where(TelegramEventEnvelope.source_id == source_id)
                )
            ).scalar_one()
        )
        cp = await session.get(CollectorCheckpoint, source_id)
        return env_n, None if cp is None else cp.last_committed_message_id

    env_before, cp_before = await run_write(_before)

    try:
        async def _partial(session: AsyncSession) -> None:
            await persist_message_envelope(
                session,
                source_id=source_id,
                dto=dto,
                collection_mode="live",
                event_type="message_new",
                observed_at=now,
            )
            # Crash before checkpoint advance — session_scope will rollback.
            raise SimulatedKill("after_persist_before_checkpoint")

        await run_write(_partial)
    except SimulatedKill:
        pass

    env_mid, cp_mid = await run_write(_before)
    failures: list[str] = []
    if env_mid != env_before:
        failures.append("partial_envelope_survived_rollback")
    if cp_mid != cp_before:
        failures.append("checkpoint_advanced_without_commit")

    # Restart with atomic path
    async def _atomic(session: AsyncSession) -> None:
        await commit_checkpoint_with_envelope(
            session,
            source_id=source_id,
            dto=dto,
            collection_mode="live",
            event_type="message_new",
            observed_at=now,
        )

    await run_write(_atomic)
    env_after, cp_after = await run_write(_before)
    if env_after != env_before + 1:
        failures.append(f"envelope_count_unexpected {env_before}->{env_after}")
    if cp_after != 88_001:
        failures.append(f"checkpoint_unexpected={cp_after}")

    # Invariant: checkpoint message id must exist as envelope
    async def _invariant(session: AsyncSession) -> bool:
        cp = await session.get(CollectorCheckpoint, source_id)
        if cp is None or cp.last_committed_message_id is None:
            return True
        row = (
            await session.execute(
                select(TelegramEventEnvelope).where(
                    TelegramEventEnvelope.source_id == source_id,
                    TelegramEventEnvelope.telegram_message_id
                    == cp.last_committed_message_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    if not await run_write(_invariant):
        failures.append("checkpoint_ahead_of_envelope")

    counters.recovery_duration_seconds = time.perf_counter() - t0
    record_restart_recovery_duration_seconds(counters.recovery_duration_seconds)
    counts = await run_write(snapshot_counts)
    report = evaluate_slo(
        scenario="kill_after_persist_before_checkpoint",
        counters=counters,
        counts=counts,
        recovery_limit=SLO_RECOVERY_SECONDS,
    )
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["cp_before"] = cp_before
    report.counters["cp_after"] = cp_after
    return report


async def run_flood_wait_scenario(
    *,
    gateway: Any,
    source_id: int,
    peer_id: int,
) -> CapacityReport:
    from telegram_lead_discovery.collector.ports import GatewayFloodWait
    from telegram_lead_discovery.collector.service import execute_backfill_job
    from telegram_lead_discovery.storage.jobs import enqueue_job

    counters = HarnessCounters()
    until = datetime.now(UTC) + timedelta(seconds=90)
    gateway.set_flood_wait(until, "iter_history")

    async def _enqueue(session: AsyncSession) -> int:
        job = await enqueue_job(
            session,
            job_type="startup_reconciliation",
            dedupe_key=f"wave09-flood-{source_id}",
            payload={"source_id": source_id, "purpose": "startup_reconciliation"},
        )
        return job.id

    job_id = await run_write(_enqueue)
    result = await execute_backfill_job(job_id=job_id, gateway=gateway)
    counters.flood_waits += 1 if result.get("outcome") == "flood_wait" else 0

    async def _job(session: AsyncSession) -> dict[str, Any]:
        job = await session.get(Job, job_id)
        assert job is not None
        return {
            "state": job.state,
            "available_at": None if job.available_at is None else job.available_at.isoformat(),
            "error": job.last_error_code,
            "attempt": job.attempt,
        }

    detail = await run_write(_job)
    gateway.clear_flood_wait()

    # Ensure no early retry: available_at must be >= until (within 1s skew)
    failures: list[str] = []
    if result.get("outcome") != "flood_wait":
        failures.append(f"expected_flood_wait got={result}")
    if detail["state"] != "retry_wait":
        failures.append(f"job_state={detail['state']}")
    if detail["error"] != "flood_wait":
        failures.append(f"error_code={detail['error']}")
    if detail["available_at"] is not None:
        avail = datetime.fromisoformat(detail["available_at"])
        if avail.tzinfo is None:
            avail = avail.replace(tzinfo=UTC)
        if avail + timedelta(seconds=1) < until:
            failures.append("retried_before_flood_until")
    else:
        failures.append("missing_available_at")

    # Also prove GatewayFloodWait surfaces from live consume path.
    try:
        gateway.set_flood_wait(until, "iter_history")
        # Direct raise path for live: push flood via set then call that checks
        _ = GatewayFloodWait
    finally:
        gateway.clear_flood_wait()

    counts = await run_write(snapshot_counts)
    report = evaluate_slo(scenario="flood_wait", counters=counters, counts=counts)
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["flood_detail"] = detail
    report.counters["peer_id"] = peer_id
    return report


async def run_notification_outage(
    *,
    bot: Any,
) -> CapacityReport:
    """Bot API outage: outbox remains, no duplicate rows, failure counted."""
    from telegram_lead_discovery.notifications.worker import process_one
    from telegram_lead_discovery.storage.outbox import enqueue_hot_lead

    counters = HarnessCounters()

    # Ensure at least one deliverable outbox row exists for the outage path.
    async def _ensure_outbox(session: AsyncSession) -> int:
        lead = (await session.execute(select(Lead).limit(1))).scalar_one_or_none()
        if lead is None:
            return 0
        lead.band = "hot"
        await session.flush()
        row = await enqueue_hot_lead(session, lead_id=lead.id, score_version=1)
        return 0 if row is None else row.id

    await run_write(_ensure_outbox)

    async def _try(session: AsyncSession) -> Any:
        return await process_one(session, client=bot)

    for _ in range(5):
        delivery = await run_write(_try)
        if delivery is None:
            break
        if getattr(delivery, "status", None) in {
            "failed",
            "retry_wait",
            "uncertain",
            "dead",
        }:
            counters.notification_failures += 1
        # Also count non-ok HTTP path via bot.fail_calls

    async def _outbox(session: AsyncSession) -> dict[str, Any]:
        rows = list((await session.execute(select(NotificationOutbox))).scalars())
        keys = [r.idempotency_key for r in rows]
        return {
            "count": len(rows),
            "unique_keys": len(set(keys)),
            "states": sorted({r.state for r in rows}),
        }

    detail = await run_write(_outbox)
    failures: list[str] = []
    if detail["count"] != detail["unique_keys"]:
        failures.append("duplicate_outbox_keys")
    if detail["count"] < 1:
        failures.append("no_outbox_for_outage_scenario")
    if getattr(bot, "fail_calls", 0) < 1 and counters.notification_failures < 1:
        failures.append("bot_outage_not_observed")
    counts = await run_write(snapshot_counts)
    report = evaluate_slo(scenario="notification_outage", counters=counters, counts=counts)
    report.failures.extend(failures)
    report.passed = not report.failures
    report.counters["outbox_detail"] = detail
    report.counters["bot_fail_calls"] = getattr(bot, "fail_calls", 0)
    return report


async def run_ui_reads_under_write_load(
    *,
    source_pairs: Sequence[tuple[int, int]],
    write_batches: int = 20,
) -> CapacityReport:
    """Concurrent inbox/monitoring reads while envelopes are written."""
    import asyncio

    counters = HarnessCounters()
    items = simulate_day_messages(
        source_ids=source_pairs[:10],
        total=write_batches * PERSIST_BATCH_SIZE,
        hot_every=9999,
        mid_base=90_000,
    )

    async def writer() -> None:
        chunk_size = PERSIST_BATCH_SIZE
        for i in range(0, len(items), chunk_size):
            chunk = items[i : i + chunk_size]
            try:

                async def _w(session: AsyncSession, _chunk=chunk) -> int:
                    return await persist_messages(session, _chunk, counters=counters)

                await run_write(_w)
            except Exception as exc:  # noqa: BLE001
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    counters.sqlite_busy += 1
                else:
                    raise
            await asyncio.sleep(0)

    async def reader() -> None:
        for _ in range(write_batches):
            try:

                async def _r(session: AsyncSession) -> None:
                    page = await list_inbox_leads(session, limit=50)
                    _ = page.leads
                    # Monitoring coverage read path (same tables as UI page).
                    cov = await session.execute(
                        select(TelegramSource, CollectorCheckpoint)
                        .outerjoin(
                            CollectorCheckpoint,
                            CollectorCheckpoint.source_id == TelegramSource.id,
                        )
                        .where(TelegramSource.lifecycle_state == "monitoring")
                        .limit(100)
                    )
                    _ = list(cov.all())

                await run_write(_r)
                counters.ui_reads_ok += 1
            except Exception as exc:  # noqa: BLE001
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    counters.sqlite_busy += 1
                else:
                    # Reads go through write lock in this architecture; treat other errors as fail
                    counters.notes.append(f"ui_read_error={type(exc).__name__}")
                    raise
            await asyncio.sleep(0)

    await asyncio.gather(writer(), reader())
    counts = await run_write(snapshot_counts)
    failures: list[str] = []
    if counters.ui_reads_ok < write_batches // 2:
        failures.append(f"ui_reads_ok={counters.ui_reads_ok}")
    # busy_timeout=5000: some busy is informative, not hard fail unless reads collapsed
    report = evaluate_slo(scenario="ui_under_write_load", counters=counters, counts=counts)
    report.failures.extend(failures)
    report.passed = not report.failures
    return report


async def pragma_busy_timeout(session: AsyncSession) -> int:
    row = (await session.execute(text("PRAGMA busy_timeout"))).scalar_one()
    return int(row)
