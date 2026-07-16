"""Integration — dashboard UI routes, CSRF, band filter, export (Phase 4)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import Lead, TelegramMessage, TelegramSource
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token missing in HTML"
    return match.group(1)


@pytest.fixture
async def ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        source = TelegramSource(
            telegram_id=7,
            username_normalized="ui_src",
            title="UI Source",
            source_type="channel",
            public_url="https://t.me/ui_src",
            lifecycle_state="monitoring",
            quality_score=4,
        )
        session.add(source)
        await session.flush()
        now = datetime.now(UTC)
        lead_ids: dict[str, int] = {}
        for i, band in enumerate(("hot", "warm", "cold", "irrelevant")):
            msg = TelegramMessage(
                source_id=source.id,
                telegram_message_id=100 + i,
                published_at=now - timedelta(minutes=i),
                original_text=f"lead text {band}",
                normalized_text=f"lead text {band}",
                normalized_hash=f"hash-{band}",
                permalink=f"https://t.me/ui_src/{100 + i}",
                state="active",
                is_canonical=True,
            )
            session.add(msg)
            await session.flush()
            msg.canonical_message_id = msg.id
            lead = Lead(
                canonical_message_id=msg.id,
                category="web_dev",
                band=band,
                status="new",
                last_activity_at=now - timedelta(minutes=i),
            )
            session.add(lead)
            await session.flush()
            lead_ids[band] = lead.id
        return lead_ids

    lead_ids = await run_write(_seed)
    app = create_app()
    yield paths, lead_ids, app
    await dispose_engine()


@pytest.mark.asyncio
async def test_dashboard_pages_and_band_filter(ui_env) -> None:
    _paths, lead_ids, app = ui_env
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Inbox" in home.text or "лидов" in home.text
        assert str(lead_ids["hot"]) in home.text
        assert "lead text irrelevant" not in home.text

        hot = client.get("/?band=hot")
        assert hot.status_code == 200
        assert f'/leads/{lead_ids["hot"]}' in hot.text
        assert f'/leads/{lead_ids["warm"]}' not in hot.text

        detail = client.get(f"/leads/{lead_ids['hot']}")
        assert detail.status_code == 200
        assert f"Лид #{lead_ids['hot']}" in detail.text
        assert "Смена статуса" in detail.text

        assert client.get("/sources").status_code == 200
        settings = client.get("/settings")
        assert settings.status_code == 200
        assert "notifications.delivery_mode" in settings.text
        assert "Настройки" in settings.text

        health = client.get("/health")
        assert health.status_code == 200
        assert "Состояние" in health.text or "database" in health.text

        fragment = client.get("/inbox/fragment")
        assert fragment.status_code == 200
        assert "<table>" in fragment.text


@pytest.mark.asyncio
async def test_csrf_reject_on_status_and_settings(ui_env) -> None:
    _paths, lead_ids, app = ui_env
    lead_id = lead_ids["hot"]
    with TestClient(app) as client:
        client.get(f"/leads/{lead_id}")
        bad = client.post(
            f"/leads/{lead_id}/status",
            data={"status": "reviewed", "csrf_token": "invalid-token"},
        )
        assert bad.status_code == 403
        assert "CSRF" in bad.text

        client.get("/settings")
        bad_settings = client.post(
            "/settings",
            data={
                "key": "notifications.delivery_mode",
                "value": "shadow",
                "expected_settings_version": "1",
                "csrf_token": "not-the-token",
            },
        )
        assert bad_settings.status_code == 403


@pytest.mark.asyncio
async def test_status_triage_and_export(ui_env) -> None:
    paths, lead_ids, app = ui_env
    lead_id = lead_ids["warm"]
    with TestClient(app) as client:
        detail = client.get(f"/leads/{lead_id}")
        token = _csrf(detail.text)
        updated = client.post(
            f"/leads/{lead_id}/status",
            data={"status": "reviewed", "csrf_token": token, "note": "ok"},
            follow_redirects=False,
        )
        assert updated.status_code == 303

        async def _check(session):
            lead = await session.get(Lead, lead_id)
            assert lead is not None
            return lead.status

        assert await run_write(_check) == "reviewed"

        before = list(paths.exports_dir.glob("telegram-leads-*.csv"))
        get_export = client.get("/exports/leads")
        assert get_export.status_code == 405
        assert list(paths.exports_dir.glob("telegram-leads-*.csv")) == before

        home = client.get("/")
        token = _csrf(home.text)
        preview = client.post("/exports/leads/preview", data={"csrf_token": token})
        assert preview.status_code == 200
        assert "Строк" in preview.text or "Preview" in preview.text
        token2 = _csrf(preview.text)
        created = client.post(
            "/exports/leads",
            data={"csrf_token": token2, "confirm": "ДА"},
        )
        assert created.status_code == 200
        files = list(paths.exports_dir.glob("telegram-leads-*.csv"))
        assert files
        content = files[-1].read_text(encoding="utf-8-sig")
        assert "lead_id" in content
        assert ";" in content
