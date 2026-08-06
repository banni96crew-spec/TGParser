"""ActiveClientChat v1 dashboard and SQL metrics (AT-UI-027 / AT-OBS-022)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.infrastructure.paths import (
    ensure_app_directories,
    resolve_app_paths,
)
from telegram_lead_discovery.storage.db import (
    dispose_engine,
    init_engine,
    session_scope,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    DiscoveryTerminalOutcome,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)
from telegram_lead_discovery.storage.session import (
    configure_session_factory,
    run_write,
)

T = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)


@pytest.fixture
async def active_chat_ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)
    app = create_app()
    yield app
    await dispose_engine()


def _snapshot(run_id: int, telegram_id: int, truth: str, score: int, **extra):
    defaults = {
        "username": f"source_{telegram_id}",
        "title": f"Source {truth} {telegram_id}",
        "source_type": "megagroup",
        "public_url": f"https://t.me/source_{telegram_id}",
        "band": "promising" if truth == "quality" else "weak",
        "truth_status": truth,
        "verification_scanned_count": 120,
        "verification_stop_reason": "quality_reached",
        "activity_message_count": 100,
        "activity_active_day_count": 10,
        "activity_distinct_author_count": 20,
        "client_request_count": 3,
        "client_request_author_count": 3,
        "hard_excluded_count": 1,
        "unknown_author_message_count": 2,
        "latest_client_request_at": T - timedelta(days=1),
        "qualification_version": "active-client-chat-v1",
        "qualification_reasons_json": '["quality_pass"]',
        "score_components_json": '{"requests":40,"client_authors":25}',
        "discovery_channels_json": '["global_message"]',
    }
    defaults.update(extra)
    return SourceOpportunitySnapshot(
        run_id=run_id,
        source_telegram_id=telegram_id,
        score=score,
        **defaults,
    )


@pytest.mark.asyncio
async def test_active_chat_ui_truth_counters_sort_and_privacy(active_chat_ui_env) -> None:
    async def _seed(session):
        run = DiscoveryRun(
            run_type="keyword_scouting",
            search_mode="free_only",
            state="running",
            phase="verification",
            started_at=T,
            reference_at=T,
            run_termination_reason="history_run_cap",
            counters_json=json.dumps(
                {
                    "gate_status": "inconclusive",
                    "quality_sources": 0,
                    "near_sources": 1,
                    "inconclusive_sources": 1,
                    "rejected_sources": 1,
                    "countable_client_requests": 5,
                    "distinct_client_authors": 4,
                    "history_scanned_total": 321,
                }
            ),
        )
        session.add(run)
        await session.flush()
        rows = [
            _snapshot(run.id, 104, "rejected", 99),
            _snapshot(run.id, 103, "inconclusive", 99),
            _snapshot(run.id, 102, "near", 35),
            _snapshot(run.id, 101, "quality", 60),
        ]
        session.add_all(rows)
        await session.flush()
        session.add(
            DiscoveryRunQuery(
                run_id=run.id,
                ordinal=1,
                query_kind="source_verification",
                query_text="",
                source_telegram_id=101,
                state="running",
            )
        )
        secret_author_key = "a" * 64
        session.add(
            SourceDiscoveryEvidence(
                run_id=run.id,
                source_telegram_id=101,
                source_username="source_101",
                source_title="Source quality 101",
                source_type="megagroup",
                author_key=secret_author_key,
                author_kind="user",
                telegram_message_id=1,
                published_at=T - timedelta(days=1),
                permalink="https://t.me/source_101/1",
                excerpt="Ищу разработчика для сайта",
                normalized_hash="b" * 64,
                detection_category="contractor_search",
                is_qualified=True,
                service_profiles_json='["websites"]',
                rule_set_checksum="c" * 64,
            )
        )
        return run.id, rows[-1].id, secret_author_key

    run_id, quality_id, secret_author_key = await run_write(_seed)
    with TestClient(active_chat_ui_env) as client:
        page = client.get(f"/discovery/runs/{run_id}")
        assert page.status_code == 200
        positions = [page.text.index(f"Source {truth}") for truth in (
            "quality", "near", "inconclusive", "rejected"
        )]
        assert positions == sorted(positions)
        assert "quality <span class=\"mono\">0/1</span>" in page.text
        assert "запросов <span class=\"mono\">5</span>" in page.text
        assert "Source quality 101" in page.text
        assert "Причина завершения:" in page.text
        assert "history_run_cap" in page.text

        detail = client.get(f"/discovery/results/{quality_id}")
        assert detail.status_code == 200
        for expected in (
            "100/100",
            "10/10",
            "20/20",
            "3/3",
            "active-client-chat-v1",
            "quality_pass",
            "requests=40",
            "client_authors=25",
            "Открыть в Telegram",
        ):
            assert expected in detail.text
        assert secret_author_key not in detail.text
        assert "author_key" not in detail.text


def _outcome(run_id: int, key: str, truth: str, stop: str, unknown: int):
    return DiscoveryTerminalOutcome(
        run_id=run_id,
        source_canonical_key=key,
        terminal_outcome_version=1,
        truth_status=truth,
        verification_stop_reason=stop,
        activity_message_count=100,
        activity_active_day_count=10,
        activity_distinct_author_count=20,
        client_request_count=3 if truth == "quality" else 1,
        client_request_author_count=3 if truth == "quality" else 1,
        unknown_author_message_count=unknown,
        threshold_activity_messages=True,
        threshold_activity_days=True,
        threshold_activity_authors=True,
        threshold_client_requests=truth == "quality",
        threshold_client_authors=truth == "quality",
        threshold_freshness=True,
    )


@pytest.mark.asyncio
async def test_active_chat_metrics_are_repeatable_sql_aggregates(active_chat_ui_env) -> None:
    async def _seed_run(session):
        run = DiscoveryRun(run_type="keyword_scouting", state="succeeded", finished_at=T)
        session.add(run)
        await session.flush()
        return run.id

    run_id = await run_write(_seed_run)
    with pytest.raises(RuntimeError, match="simulated_crash"):
        async with session_scope() as session:
            session.add(_outcome(run_id, "peer:1", "quality", "quality_reached", 7))
            await session.flush()
            raise RuntimeError("simulated_crash")

    with TestClient(active_chat_ui_env) as client:
        before = client.get("/metrics/discovery/active-chat").json()
        assert all(item["value"] == 0 for item in before["metrics"])

    async def _commit(session):
        session.add_all(
            [
                _outcome(run_id, "peer:1", "quality", "quality_reached", 7),
                _outcome(run_id, "peer:2", "near", "history_exhausted", 2),
            ]
        )

    await run_write(_commit)
    with TestClient(active_chat_ui_env) as client:
        first = client.get("/metrics/discovery/active-chat")
        second = client.get("/metrics/discovery/active-chat")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        payload = first.json()
        samples = {
            (item["name"], tuple(sorted(item["labels"].items()))): item["value"]
            for item in payload["metrics"]
        }
        assert samples[("discovery_active_chat_quality_total", ())] == 1
        assert samples[(
            "discovery_active_chat_candidates_total", (("truth_status", "near"),)
        )] == 1
        assert samples[(
            "discovery_active_chat_unknown_author_messages_total", ()
        )] == 9
        serialized = json.dumps(payload)
        for forbidden in ("run_id", "telegram_id", "author_key", "peer:1"):
            assert forbidden not in serialized
