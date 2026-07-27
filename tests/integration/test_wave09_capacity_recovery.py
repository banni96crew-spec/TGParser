"""Wave 09 Part A — isolated capacity / recovery harness (temp DB + fake gateway).

Proves NFR-PERF-006..008 and NFR-REL-008 on harness only.
Part B (live Windows pilot) is NOT executed here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.harness.capacity_recovery import (
    SLO_BURST_EVENTS,
    SLO_MONITORING_SOURCES,
    CapacityReport,
    make_dto,
    run_burst_capacity,
    run_duplicate_replay,
    run_edits_deletes,
    run_flood_wait_scenario,
    run_kill_after_fetch_before_persist,
    run_kill_after_persist_before_checkpoint,
    run_notification_outage,
    run_steady_capacity,
    run_ui_reads_under_write_load,
    seed_monitoring_sources,
)

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_source
from telegram_lead_discovery.detection.loader import get_default_loader
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults, update_setting
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.jobs import enqueue_job
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.session import (
    configure_session_factory,
    reset_write_lock,
    run_write,
)

ARTIFACT_DIR = (
    Path(__file__).resolve().parents[2]
    / ".omc"
    / "artifacts"
    / "lead-discovery-remediation"
    / "wave-09"
)


class FlakyBotClient:
    """Fake Bot API: fails first N posts, then succeeds. No network."""

    def __init__(self, *, fail_first: int = 3) -> None:
        self.fail_first = fail_first
        self.calls = 0
        self.fail_calls = 0

    async def post(self, url: str, *, json: dict | None = None) -> Any:
        self.calls += 1
        if self.calls <= self.fail_first:
            self.fail_calls += 1

            class _Fail:
                status_code = 503

                def json(self) -> dict[str, Any]:
                    return {"ok": False, "description": "harness_outage"}

            return _Fail()

        class _Ok:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"ok": True, "result": {"message_id": 9009}}

        return _Ok()


@pytest.fixture
async def harness_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated temp LOCALAPPDATA — never the operator live DB."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-tests")
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:WAVE09-HARNESS-TOKEN")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-1009009")
    paths = ensure_app_directories(resolve_app_paths())
    # Guard: path must live under tmp_path
    assert str(paths.database_path).startswith(str(tmp_path))
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    get_default_loader().clear_cache()

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        await update_setting(
            session,
            key="notifications.delivery_mode",
            typed_value="live",
            expected_settings_version=1,
            change_source="test",
        )
        return await seed_monitoring_sources(session, count=SLO_MONITORING_SOURCES)

    pairs = await run_write(_seed)
    yield paths, pairs
    await dispose_engine()
    reset_write_lock()


def _write_reports(reports: list[CapacityReport]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_DIR / "harness-report.json"
    payload = {
        "wave": "09A",
        "part_b": "NOT_RUN",
        "part_b_reason": "awaiting explicit operator approval (HC-6)",
        "reports": [r.to_dict() for r in reports],
        "all_passed": all(r.passed for r in reports),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


@pytest.mark.asyncio
async def test_wave09a_capacity_recovery_harness(harness_env) -> None:
    paths, pairs = harness_env
    reports: list[CapacityReport] = []

    # --- NFR-PERF-006 / 008 steady ---
    reports.append(await run_steady_capacity(source_pairs=pairs))

    # --- NFR-PERF-007 / 008 burst ---
    reports.append(await run_burst_capacity(source_pairs=pairs, burst_events=SLO_BURST_EVENTS))

    # --- correctness: 10% dup replay ---
    reports.append(await run_duplicate_replay(source_pairs=pairs, base_count=200))

    # --- edits / deletes ---
    sid0, peer0 = pairs[0]
    reports.append(await run_edits_deletes(source_id=sid0, peer_id=peer0))

    # --- kill after fetch before persist ---
    sid1, peer1 = pairs[50]
    username1 = f"wave09_src_{50:03d}"
    snap1 = make_source(telegram_id=peer1, username=username1)
    gw = FakeTelegramGateway(sources={username1: snap1})
    now = datetime.now(UTC)
    history = [
        make_dto(
            source_id=sid1,
            peer_id=peer1,
            mid=mid,
            text=f"reconcile msg {mid}",
            published=now - timedelta(minutes=60 - (mid % 60)),
        )
        for mid in range(200_001, 200_021)
    ]
    gw.register_messages_for_peer(peer1, history)

    async def _reset_cp(session):
        from telegram_lead_discovery.storage.models import CollectorCheckpoint

        cp = await session.get(CollectorCheckpoint, sid1)
        if cp is not None:
            cp.last_committed_message_id = 200_000
            cp.last_committed_published_at = now - timedelta(hours=2)
            await session.flush()

    await run_write(_reset_cp)

    async def _job(session):
        job = await enqueue_job(
            session,
            job_type="startup_reconciliation",
            dedupe_key=f"wave09-kill-fetch-{sid1}",
            payload={"source_id": sid1, "purpose": "startup_reconciliation"},
        )
        return job.id

    job_id = await run_write(_job)
    reports.append(
        await run_kill_after_fetch_before_persist(
            gateway=gw,
            source_id=sid1,
            peer_id=peer1,
            job_id=job_id,
        )
    )

    # --- kill after persist before checkpoint (atomic TX rollback) ---
    sid2, peer2 = pairs[2]
    reports.append(
        await run_kill_after_persist_before_checkpoint(source_id=sid2, peer_id=peer2)
    )

    # --- FloodWait ---
    sid3, peer3 = pairs[3]
    username3 = f"wave09_src_{3:03d}"
    snap3 = make_source(telegram_id=peer3, username=username3)
    gw3 = FakeTelegramGateway(sources={username3: snap3})
    gw3.register_messages_for_peer(
        peer3,
        [
            make_dto(
                source_id=sid3,
                peer_id=peer3,
                mid=1,
                text="flood bait",
                published=now,
            )
        ],
    )
    reports.append(
        await run_flood_wait_scenario(gateway=gw3, source_id=sid3, peer_id=peer3)
    )

    # --- notification outage ---
    bot = FlakyBotClient(fail_first=3)
    reports.append(await run_notification_outage(bot=bot))

    # --- UI reads under write load ---
    reports.append(await run_ui_reads_under_write_load(source_pairs=pairs, write_batches=20))

    report_path = _write_reports(reports)
    assert report_path.is_file()
    assert str(paths.database_path).startswith(str(Path(paths.database_path).anchor) or "")

    failed = [r for r in reports if not r.passed]
    assert not failed, (
        "Wave 09A SLO failures:\n"
        + "\n".join(f"- {r.scenario}: {r.failures}" for r in failed)
    )


@pytest.mark.asyncio
async def test_wave09a_temp_db_not_live_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard guard: harness must not resolve to the operator product live DB path."""
    import os

    real_local = os.environ.get("LOCALAPPDATA", "")
    live_db = Path(real_local) / "TelegramLeadDiscovery" / "data" / "app.sqlite3"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    assert str(tmp_path) in str(paths.database_path)
    assert paths.database_path.resolve() != live_db.resolve()
