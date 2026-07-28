"""Integration — approve source → initial_backfill via fake gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.collector.ports import SourceSnapshot, TelegramMessageDTO
from telegram_lead_discovery.collector.service import handle_backfill_job
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.service import (
    SourceLifecycleError,
    add_manual_candidate,
    approve_source,
    disable_source,
    import_csv,
    normalize_username,
    pause_source,
    reconsider_source,
    reject_source,
    resume_source,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    Job,
    SourceApprovalEvent,
    SourceDiscoveryEvent,
    TelegramEventEnvelope,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    await run_write(seed_defaults)
    yield paths
    await dispose_engine()


def test_src_001_normalize_username() -> None:
    assert normalize_username("https://t.me/Test_Channel/?x=1") == "test_channel"


@pytest.mark.asyncio
async def test_csv_import_preserves_partial_results_and_rows(db_env) -> None:
    async def _import(session):
        run, results = await import_csv(
            session,
            csv_text=(
                "source_ref\n"
                "@alpha_channel\n"
                "bad!\n"
                "\n"
                "https://t.me/beta_channel\n"
            ),
        )
        return run.id, run.root_source_ids_json, results

    run_id, root_ids_json, results = await run_write(_import)
    assert [(row.line_no, row.raw, row.ok, row.error_code) for row in results] == [
        (2, "@alpha_channel", True, None),
        (3, "bad!", False, "invalid_username"),
        (4, "https://t.me/beta_channel", True, None),
    ]
    assert root_ids_json == str([results[0].source_id, results[2].source_id])

    async def _events(session):
        rows = await session.execute(
            select(SourceDiscoveryEvent)
            .where(SourceDiscoveryEvent.run_id == run_id)
            .order_by(SourceDiscoveryEvent.id.asc())
        )
        return list(rows.scalars().all())

    events = await run_write(_events)
    assert [event.method for event in events] == ["seed_import", "seed_import"]
    assert [event.raw_reference for event in events] == [
        "@alpha_channel",
        "https://t.me/beta_channel",
    ]


@pytest.mark.asyncio
async def test_csv_import_preserves_validation_and_row_cap(db_env) -> None:
    async def _missing_header(session):
        with pytest.raises(ValueError, match="^csv_missing_source_ref$"):
            await import_csv(session, csv_text="wrong\n@alpha_channel\n")

    await run_write(_missing_header)

    async def _too_large(session):
        with pytest.raises(ValueError, match="^csv_too_large$"):
            await import_csv(session, csv_text="source_ref\n" + "x" * (1024 * 1024))

    await run_write(_too_large)

    csv_text = "source_ref\n" + "\n".join("bad!" for _ in range(1001))

    async def _row_cap(session):
        _run, results = await import_csv(session, csv_text=csv_text)
        return results

    results = await run_write(_row_cap)
    assert len(results) == 1001
    assert results[-1].line_no == 1002
    assert results[-1].error_code == "row_cap"


@pytest.mark.asyncio
async def test_source_lifecycle_preserves_state_events_and_idempotency(db_env) -> None:
    snap = SourceSnapshot(
        schema_version=1,
        telegram_id=3003,
        username="lifecycle_test",
        title="Lifecycle Test",
        source_type="channel",
        public_url="https://t.me/lifecycle_test",
        accessible=True,
    )
    gateway = FakeTelegramGateway(sources={"lifecycle_test": snap})

    async def _exercise(session):
        source, _run = await add_manual_candidate(
            session,
            username_or_url="@lifecycle_test",
        )
        source_id = source.id
        await reject_source(session, source_id=source_id, reason_code="low_signal")
        await reject_source(session, source_id=source_id, reason_code="low_signal")
        await reconsider_source(session, source_id=source_id)
        await approve_source(session, source_id=source_id, gateway=gateway)
        await pause_source(session, source_id=source_id)
        await pause_source(session, source_id=source_id)
        await resume_source(session, source_id=source_id)
        await disable_source(session, source_id=source_id)
        with pytest.raises(SourceLifecycleError, match="invalid_transition"):
            await resume_source(session, source_id=source_id)
        with pytest.raises(SourceLifecycleError, match="invalid_reject_reason"):
            await reject_source(session, source_id=source_id, reason_code="unknown")
        return source_id

    source_id = await run_write(_exercise)

    async def _state(session):
        source = await session.get(TelegramSource, source_id)
        rows = await session.execute(
            select(SourceApprovalEvent)
            .where(SourceApprovalEvent.source_id == source_id)
            .order_by(SourceApprovalEvent.id.asc())
        )
        return source, list(rows.scalars().all())

    source, events = await run_write(_state)
    assert source is not None
    assert source.lifecycle_state == "disabled"
    assert source.disabled_at is not None
    assert [event.to_state for event in events] == [
        "rejected",
        "candidate",
        "monitoring",
        "paused",
        "monitoring",
        "disabled",
    ]


@pytest.mark.asyncio
async def test_approve_enqueues_backfill_and_persists(db_env) -> None:
    from datetime import UTC, datetime

    snap = SourceSnapshot(
        schema_version=1,
        telegram_id=1001,
        username="test_channel",
        title="Test Channel",
        source_type="channel",
        public_url="https://t.me/test_channel",
        accessible=True,
    )
    gateway = FakeTelegramGateway(sources={"test_channel": snap})
    now = datetime.now(UTC)
    gateway.register_messages(
        1,  # will be remapped after source insert — set after create
        [],
    )

    async def _add(session):
        source, _run = await add_manual_candidate(
            session, username_or_url="https://t.me/Test_Channel", gateway=gateway
        )
        return source.id

    source_id = await run_write(_add)

    gateway.register_messages(
        source_id,
        [
            TelegramMessageDTO(
                schema_version=1,
                source_id=source_id,
                telegram_message_id=10,
                published_at=now,
                text="Нужно разработать сайт, бюджет 150000 ₽.",
                permalink="https://t.me/test_channel/10",
            )
        ],
    )

    async def _approve(session):
        return await approve_source(session, source_id=source_id, gateway=gateway)

    source = await run_write(_approve)
    assert source.lifecycle_state == "monitoring"

    async def _job(session):
        result = await session.execute(
            select(Job).where(
                Job.job_type == "initial_backfill",
                Job.dedupe_key == f"initial_backfill:{source_id}",
            )
        )
        return result.scalar_one()

    job = await run_write(_job)
    assert job.state == "queued"

    async def _run_backfill(session):
        job_row = await session.get(Job, job.id)
        assert job_row is not None
        return await handle_backfill_job(session, job_row, gateway)

    outcome = await run_write(_run_backfill)
    assert outcome["outcome"] == "succeeded"
    assert outcome["persisted"] == 1

    async def _envelopes(session):
        result = await session.execute(select(TelegramEventEnvelope))
        return list(result.scalars().all())

    envelopes = await run_write(_envelopes)
    assert len(envelopes) == 1
    assert envelopes[0].processing_state == "queued"

    async def _source(session):
        return await session.get(TelegramSource, source_id)

    refreshed = await run_write(_source)
    assert refreshed is not None
    assert refreshed.lifecycle_state == "monitoring"


@pytest.mark.asyncio
async def test_approve_commits_before_telegram_validate(db_env) -> None:
    """SQLite write txn must not span gateway.validate_source (database is locked)."""
    snap = SourceSnapshot(
        schema_version=1,
        telegram_id=2002,
        username="lock_test",
        title="Lock Test",
        source_type="channel",
        public_url="https://t.me/lock_test",
        accessible=True,
    )
    order: list[str] = []

    async def _add(session):
        source, _run = await add_manual_candidate(
            session, username_or_url="@lock_test", gateway=None
        )
        return source.id

    source_id = await run_write(_add)

    class OrderingGateway(FakeTelegramGateway):
        async def validate_source(self, ref):  # noqa: ANN001
            order.append("validate")
            return await super().validate_source(ref)

    gw = OrderingGateway(sources={"lock_test": snap})

    async def _approve(session):
        real_commit = session.commit

        async def tracking_commit():
            order.append("commit")
            return await real_commit()

        session.commit = tracking_commit  # type: ignore[method-assign]
        return await approve_source(session, source_id=source_id, gateway=gw)

    source = await run_write(_approve)
    assert source.lifecycle_state == "monitoring"
    assert "validate" in order
    assert order.index("commit") < order.index("validate")
