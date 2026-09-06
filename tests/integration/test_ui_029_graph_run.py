"""AT-UI-029 — graph run page on existing discovery URLs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import (
    ensure_app_directories,
    resolve_app_paths,
)
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.graph_discovery import (
    start_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    ensure_seed_keyword_profile,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import DiscoveryRun, Job, TelegramSource
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token missing in HTML"
    return match.group(1)


@pytest.fixture
async def discovery_ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-ui-tests")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        return await ensure_seed_keyword_profile(session)

    seed = await run_write(_seed)
    app = create_app()
    app.state.telegram_credentials_present = True
    yield paths, seed, app
    await dispose_engine()


async def _start_graph(*, telegram_id: int, username: str) -> tuple[int, int]:
    async with session_scope() as session:
        source = TelegramSource(
            telegram_id=telegram_id,
            username_normalized=username,
            title=username,
            source_type="channel",
            public_url=f"https://t.me/{username}",
            lifecycle_state="monitoring",
            quality_score=3,
        )
        session.add(source)
        await session.flush()
        started = await start_graph_discovery_run(
            session, seed_source_ids=[source.id]
        )
        await session.commit()
        return started.run.id, started.job.id


@pytest.mark.asyncio
async def test_graph_run_page_cancel_and_keyword_regression(discovery_ui_env) -> None:
    _paths, seed, app = discovery_ui_env
    run_id, _job_id = await _start_graph(telegram_id=501, username="ui_graph_seed")
    with TestClient(app) as client:
        page = client.get(f"/discovery/runs/{run_id}")
        assert page.status_code == 200
        assert "status-fragment" not in page.text
        assert "results-fragment" not in page.text
        assert 'hx-get="/discovery/runs/' not in page.text
        assert 'name="csrf_token"' in page.text
        token = _csrf(page.text)
        version = re.search(r'name="expected_version"\s+value="([^"]+)"', page.text)
        assert version is not None
        bad = client.post(
            f"/discovery/runs/{run_id}/cancel",
            data={"csrf_token": "invalid", "expected_version": version.group(1)},
            follow_redirects=False,
        )
        assert bad.status_code == 403
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            assert run.state == "queued"
        ok = client.post(
            f"/discovery/runs/{run_id}/cancel",
            data={"csrf_token": token, "expected_version": version.group(1)},
            follow_redirects=False,
        )
        assert ok.status_code == 303
        assert ok.headers["location"] == f"/discovery/runs/{run_id}"
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            assert run.state == "cancelled"

    run_id, job_id = await _start_graph(telegram_id=502, username="ui_graph_seed_2")
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        job.state = "running"
        run = await session.get(DiscoveryRun, run_id)
        run.state = "running"
        await session.commit()
    with TestClient(app) as client:
        page = client.get(f"/discovery/runs/{run_id}")
        token = _csrf(page.text)
        version = re.search(r'name="expected_version"\s+value="([^"]+)"', page.text)
        assert version is not None
        resp = client.post(
            f"/discovery/runs/{run_id}/cancel",
            data={
                "csrf_token": token,
                "expected_version": version.group(1),
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            assert run.state == "cancelling"
            run.state = "cancelled"
            run.finished_at = run.finished_at
            job = await session.get(Job, job_id)
            job.state = "cancelled"
            await session.commit()

    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        started = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        assert started.status_code == 303
        keyword_id = int(started.headers["location"].rsplit("/", 1)[-1])
        kw = client.get(f"/discovery/runs/{keyword_id}")
        assert kw.status_code == 200
        assert "status-fragment" in kw.text
        token = _csrf(kw.text)
        version = re.search(r'name="expected_version"\s+value="([^"]+)"', kw.text)
        assert version is not None
        cancel = client.post(
            f"/discovery/runs/{keyword_id}/cancel",
            data={
                "csrf_token": token,
                "expected_version": version.group(1),
            },
            follow_redirects=False,
        )
        assert cancel.status_code == 303
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, keyword_id)
            assert run.state in {"cancelling", "cancelled"}
