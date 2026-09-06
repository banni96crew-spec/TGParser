"""AT-UI-028 — keyword start seed_refs CSRF and optimistic version."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.graph_discovery import JOB_TYPE_GRAPH_DISCOVERY
from telegram_lead_discovery.source_discovery.profile_service import ensure_seed_keyword_profile
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import DiscoveryRun, DiscoveryRunQuery, Job
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token missing in HTML"
    return match.group(1)


def _expected_version(html: str) -> int:
    match = re.search(r'name="expected_version"\s+value="(\d+)"', html)
    assert match, "expected_version missing in HTML"
    return int(match.group(1))


@pytest.fixture
async def ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    yield seed, app
    await dispose_engine()


async def _run_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(DiscoveryRun)) or 0)


@pytest.mark.asyncio
async def test_at_ui_028_seed_refs_bounds_csrf_and_stale_version(ui_env) -> None:
    seed, app = ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        assert index.status_code == 200
        assert 'name="seed_refs"' in index.text
        token = _csrf(index.text)
        version = _expected_version(index.text)

        empty = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": "",
            },
            follow_redirects=False,
        )
        assert empty.status_code == 303
        run_id = int(empty.headers["location"].rsplit("/", 1)[-1])

        async def _empty_seeds(session):
            rows = list(
                (
                    await session.execute(
                        select(DiscoveryRunQuery).where(
                            DiscoveryRunQuery.run_id == run_id,
                            DiscoveryRunQuery.query_kind == "operator_seed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            jobs = list((await session.execute(select(Job))).scalars().all())
            return rows, jobs

        seed_rows, jobs = await run_write(_empty_seeds)
        assert seed_rows == []
        assert all(job.job_type != JOB_TYPE_GRAPH_DISCOVERY for job in jobs)

        before = await run_write(_run_count)
        csrf_denied = client.post(
            "/discovery/runs",
            data={
                "csrf_token": "invalid",
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": "@chatok",
            },
            follow_redirects=False,
        )
        assert csrf_denied.status_code == 403
        assert await run_write(_run_count) == before

        stale = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version + 9,
                "seed_refs": "@chatok",
            },
            follow_redirects=False,
        )
        assert stale.status_code == 409
        assert await run_write(_run_count) == before

        too_many = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": "\n".join(f"seed{i:02d}x" for i in range(26)),
            },
            follow_redirects=False,
        )
        assert too_many.status_code == 422
        assert "seed_refs_limit_exceeded" in too_many.text
        assert await run_write(_run_count) == before

        invalid = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": "???",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 422
        assert "invalid_seed_ref" in invalid.text
        assert await run_write(_run_count) == before


@pytest.mark.asyncio
async def test_at_ui_028_twenty_five_seed_lines(ui_env) -> None:
    seed, app = ui_env
    lines = "\n".join(f"seed{i:02d}x" for i in range(25))
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        version = _expected_version(index.text)
        started = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": lines,
            },
            follow_redirects=False,
        )
        assert started.status_code == 303
        run_id = int(started.headers["location"].rsplit("/", 1)[-1])

        async def _rows(session):
            return list(
                (
                    await session.execute(
                        select(DiscoveryRunQuery).where(
                            DiscoveryRunQuery.run_id == run_id,
                            DiscoveryRunQuery.query_kind == "operator_seed",
                        )
                    )
                )
                .scalars()
                .all()
            )

        rows = await run_write(_rows)
        assert len(rows) == 25


@pytest.mark.asyncio
async def test_at_ui_028_one_seed_line(ui_env) -> None:
    seed, app = ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        version = _expected_version(index.text)
        started = client.post(
            "/discovery/runs",
            data={
                "csrf_token": token,
                "profile_id": seed.profile.id,
                "expected_version": version,
                "seed_refs": "@chatok",
            },
            follow_redirects=False,
        )
        assert started.status_code == 303
        run_id = int(started.headers["location"].rsplit("/", 1)[-1])

        async def _rows(session):
            return list(
                (
                    await session.execute(
                        select(DiscoveryRunQuery).where(
                            DiscoveryRunQuery.run_id == run_id,
                            DiscoveryRunQuery.query_kind == "operator_seed",
                        )
                    )
                )
                .scalars()
                .all()
            )

        rows = await run_write(_rows)
        assert len(rows) == 1
        assert rows[0].query_text == "@chatok"
