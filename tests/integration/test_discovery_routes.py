"""Integration — keyword discovery dashboard routes (step-16 / UI-017/018)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.dashboard.discovery_routes import ZERO_STARS_LABEL
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.profile_service import ensure_seed_keyword_profile
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import SourceOpportunitySnapshot
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


@pytest.mark.asyncio
async def test_discovery_nav_and_index(discovery_ui_env) -> None:
    _paths, seed, app = discovery_ui_env
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Разведка источников" in home.text
        assert 'href="/discovery"' in home.text

        page = client.get("/discovery")
        assert page.status_code == 200
        assert ZERO_STARS_LABEL in page.text
        assert "allow_paid" not in page.text.lower()
        assert "stars_amount" not in page.text.lower()
        assert seed.profile.name in page.text
        assert 'class="nav-link is-active"' in page.text
        assert "Разведка источников" in page.text


@pytest.mark.asyncio
async def test_discovery_csrf_and_303_promote_cancel(discovery_ui_env) -> None:
    _paths, seed, app = discovery_ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)

        bad = client.post(
            "/discovery/runs",
            data={"csrf_token": "invalid", "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        assert bad.status_code == 403

        started = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        assert started.status_code == 303
        assert started.headers["location"].startswith("/discovery/runs/")
        run_id = int(started.headers["location"].rsplit("/", 1)[-1])

        detail = client.get(f"/discovery/runs/{run_id}")
        assert detail.status_code == 200
        assert 'hx-trigger="every 5s"' in detail.text
        assert "/static/vendor/htmx-2.0.10.min.js" in detail.text
        assert "cdn.jsdelivr" not in detail.text.lower()
        assert "unpkg.com" not in detail.text.lower()
        token2 = _csrf(detail.text)
        version_match = re.search(
            r'name="expected_version"\s+value="(\d+)"', detail.text
        )
        assert version_match
        expected_version = int(version_match.group(1))

        cancel = client.post(
            f"/discovery/runs/{run_id}/cancel",
            data={
                "csrf_token": token2,
                "expected_version": expected_version,
            },
            follow_redirects=False,
        )
        assert cancel.status_code == 303
        assert cancel.headers["location"] == f"/discovery/runs/{run_id}"

        async def _add_opportunity(session):
            snap = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=9001,
                username="opp_ui",
                title="Opp UI",
                source_type="megagroup",
                public_url="https://t.me/opp_ui",
                score=70,
                band="strong",
                score_components_json="{}",
                discovery_channels_json='["global_message"]',
                review_state="unreviewed",
                version=1,
            )
            session.add(snap)
            await session.flush()
            return snap.id

        opp_id = await run_write(_add_opportunity)
        result_page = client.get(f"/discovery/results/{opp_id}")
        assert result_page.status_code == 200
        assert ZERO_STARS_LABEL in result_page.text
        assert "Одобрить мониторинг" not in result_page.text
        token3 = _csrf(result_page.text)

        promote = client.post(
            f"/discovery/results/{opp_id}/promote",
            data={"csrf_token": token3, "expected_version": 1},
            follow_redirects=False,
        )
        assert promote.status_code == 303
        assert promote.headers["location"] == f"/discovery/results/{opp_id}"

        after = client.get(f"/discovery/results/{opp_id}")
        assert after.status_code == 200
        assert "promoted" in after.text
        assert 'rel="noopener noreferrer"' in after.text
        assert "Одобрить мониторинг" not in after.text
        assert "Одобрить в Источниках" in after.text
        assert "/sources#source-" in after.text

        index_after = client.get("/discovery")
        assert index_after.status_code == 200
        assert f'href="/discovery/runs/{run_id}"' in index_after.text
        assert "Открыть" in index_after.text

        status = client.get(f"/discovery/runs/{run_id}/status-fragment")
        assert status.status_code == 200
        assert "progress-bar" in status.text
        assert f'hx-get="/discovery/runs/{run_id}/status-fragment"' in status.text
        assert 'hx-trigger="every 5s"' in status.text
        assert "Dismissed-suppressed:" in status.text

        results = client.get(f"/discovery/runs/{run_id}/results-fragment")
        assert results.status_code == 200
        assert "discovery-filters" in results.text
        assert "Opp UI" in results.text
        assert f'href="/discovery/results/{opp_id}"' in results.text

@pytest.mark.asyncio
async def test_discovery_htmx_vendored_locally(discovery_ui_env) -> None:
    _paths, _seed, app = discovery_ui_env
    with TestClient(app) as client:
        page = client.get("/discovery")
        assert page.status_code == 200
        assert 'src="/static/vendor/htmx-2.0.10.min.js"' in page.text
        assert "cdn." not in page.text.lower()

        vendor = client.get("/static/vendor/htmx-2.0.10.min.js")
        assert vendor.status_code == 200
        assert b"htmx" in vendor.content[:200].lower() or b"var htmx" in vendor.content[:80]

        license_file = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "telegram_lead_discovery"
            / "dashboard"
            / "static"
            / "vendor"
            / "htmx-2.0.10.LICENSE.txt"
        )
        assert license_file.is_file()
        source_file = license_file.with_name("SOURCE.txt")
        assert source_file.is_file()
        assert "2.0.10" in source_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_discovery_retention_evidence_message(discovery_ui_env) -> None:
    from telegram_lead_discovery.dashboard.discovery_routes import (
        EVIDENCE_RETENTION_MESSAGE,
    )
    from telegram_lead_discovery.storage.models import SourceDiscoveryEvidence

    _paths, seed, app = discovery_ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        started = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        run_id = int(started.headers["location"].rsplit("/", 1)[-1])

        async def _seed_purged(session):
            from datetime import UTC, datetime

            snap = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=9002,
                username="purged_ui",
                title="Purged UI",
                source_type="channel",
                public_url="https://t.me/purged_ui",
                score=40,
                band="review",
                score_components_json="{}",
                discovery_channels_json='["directory"]',
                review_state="unreviewed",
                sample_message_count=1,
                version=1,
            )
            session.add(snap)
            await session.flush()
            session.add(
                SourceDiscoveryEvidence(
                    run_id=run_id,
                    source_telegram_id=9002,
                    source_username="purged_ui",
                    source_title="Purged UI",
                    source_type="channel",
                    telegram_message_id=1,
                    published_at=datetime(2026, 1, 1, tzinfo=UTC),
                    permalink="https://t.me/purged_ui/1",
                    excerpt="",
                    normalized_hash="abc",
                    matched_query_ordinals_json="[1]",
                    discovery_channels_json='["directory"]',
                    detection_category="service_request",
                    is_qualified=True,
                    service_profiles_json='["web"]',
                    rule_set_checksum="x",
                )
            )
            await session.flush()
            return snap.id

        opp_id = await run_write(_seed_purged)
        page = client.get(f"/discovery/results/{opp_id}")
        assert page.status_code == 200
        assert EVIDENCE_RETENTION_MESSAGE in page.text
        assert "Одобрить мониторинг" not in page.text


@pytest.mark.asyncio
async def test_discovery_profile_create_version_and_invalid_queries(
    discovery_ui_env,
) -> None:
    _paths, _seed, app = discovery_ui_env
    with TestClient(app) as client:
        form = client.get("/discovery/profiles/new")
        assert form.status_code == 200
        assert ZERO_STARS_LABEL in form.text
        token = _csrf(form.text)

        invalid = client.post(
            "/discovery/profiles",
            data={
                "csrf_token": token,
                "name": "bad-profile",
                "post_queries": "ab\nнужен сайт",
                "directory_queries": "",
                "additional_exclusions": "",
                "source_scope": "groups",
                "required_service_profiles": "",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 422

        created = client.post(
            "/discovery/profiles",
            data={
                "csrf_token": token,
                "name": "ui-profile-a",
                "post_queries": "нужен сайт\nищу разработчика",
                "directory_queries": "ecommerce",
                "additional_exclusions": "",
                "source_scope": "groups",
                "required_service_profiles": "",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"].startswith("/discovery/profiles/")
        profile_id = int(created.headers["location"].rsplit("/", 1)[-1])

        detail = client.get(f"/discovery/profiles/{profile_id}")
        assert detail.status_code == 200
        assert "ui-profile-a" in detail.text
        token2 = _csrf(detail.text)
        version_match = re.search(
            r'name="expected_version"\s+value="(\d+)"', detail.text
        )
        assert version_match
        expected_version = int(version_match.group(1))

        versioned = client.post(
            f"/discovery/profiles/{profile_id}/versions",
            data={
                "csrf_token": token2,
                "expected_version": expected_version,
                "post_queries": "нужен сайт\nищу разработчика\nнужен бот",
                "directory_queries": "ecommerce",
                "additional_exclusions": "",
                "source_scope": "all",
                "required_service_profiles": "",
            },
            follow_redirects=False,
        )
        assert versioned.status_code == 303
        assert versioned.headers["location"] == f"/discovery/profiles/{profile_id}"

        after = client.get(f"/discovery/profiles/{profile_id}")
        assert after.status_code == 200
        assert re.search(r'name="expected_version"\s+value="2"', after.text)


@pytest.mark.asyncio
async def test_discovery_duplicate_start_conflict_and_filters(discovery_ui_env) -> None:
    _paths, seed, app = discovery_ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        first = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        assert first.status_code == 303
        run_id = int(first.headers["location"].rsplit("/", 1)[-1])

        conflict = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        assert conflict.status_code == 409
        assert "active_keyword_run" in conflict.text

        async def _seed_opps(session):
            strong = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=9101,
                username="filter_strong",
                title="Filter Strong",
                source_type="megagroup",
                public_url="https://t.me/filter_strong",
                score=90,
                band="promising",
                score_components_json="{}",
                discovery_channels_json='["global_message"]',
                review_state="unreviewed",
                version=1,
            )
            weak = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=9102,
                username="filter_weak",
                title="Filter Weak",
                source_type="channel",
                public_url="https://t.me/filter_weak",
                score=10,
                band="weak",
                score_components_json="{}",
                discovery_channels_json='["directory"]',
                review_state="unreviewed",
                version=1,
            )
            session.add_all([strong, weak])
            await session.flush()

        await run_write(_seed_opps)

        filtered = client.get(
            f"/discovery/runs/{run_id}/results-fragment",
            params={"band": "promising"},
        )
        assert filtered.status_code == 200
        assert "Filter Strong" in filtered.text
        assert "Filter Weak" not in filtered.text
        assert 'name="band"' in filtered.text


@pytest.mark.asyncio
async def test_discovery_evidence_escaping_and_repeated_promote(
    discovery_ui_env,
) -> None:
    from datetime import UTC, datetime

    from telegram_lead_discovery.storage.models import SourceDiscoveryEvidence

    _paths, seed, app = discovery_ui_env
    with TestClient(app) as client:
        index = client.get("/discovery")
        token = _csrf(index.text)
        started = client.post(
            "/discovery/runs",
            data={"csrf_token": token, "profile_id": seed.profile.id},
            follow_redirects=False,
        )
        run_id = int(started.headers["location"].rsplit("/", 1)[-1])

        xss = '<script>alert("xss")</script>'

        async def _seed_xss(session):
            snap = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=9201,
                username="xss_src",
                title=f"Title {xss}",
                source_type="channel",
                public_url="https://t.me/xss_src",
                score=55,
                band="review",
                score_components_json="{}",
                discovery_channels_json='["global_message"]',
                review_state="unreviewed",
                sample_message_count=1,
                version=1,
            )
            session.add(snap)
            await session.flush()
            session.add(
                SourceDiscoveryEvidence(
                    run_id=run_id,
                    source_telegram_id=9201,
                    source_username="xss_src",
                    source_title="xss",
                    source_type="channel",
                    telegram_message_id=7,
                    published_at=datetime(2026, 7, 1, tzinfo=UTC),
                    permalink="https://t.me/xss_src/7",
                    excerpt=xss,
                    normalized_hash="xsshash",
                    matched_query_ordinals_json="[1]",
                    discovery_channels_json='["global_message"]',
                    detection_category="service_request",
                    is_qualified=True,
                    service_profiles_json='["web"]',
                    rule_set_checksum="x",
                )
            )
            await session.flush()
            return snap.id

        opp_id = await run_write(_seed_xss)
        page = client.get(f"/discovery/results/{opp_id}")
        assert page.status_code == 200
        assert xss not in page.text
        assert "&lt;script&gt;" in page.text or "&#34;" in page.text or "&lt;" in page.text

        token2 = _csrf(page.text)
        first = client.post(
            f"/discovery/results/{opp_id}/promote",
            data={"csrf_token": token2, "expected_version": 1},
            follow_redirects=False,
        )
        assert first.status_code == 303

        after = client.get(f"/discovery/results/{opp_id}")
        assert after.status_code == 200
        assert "promoted" in after.text
        version_match = re.search(r"Version:\s*<span class=\"mono\">(\d+)</span>", after.text)
        assert version_match
        # Promoted detail hides action forms; take CSRF from discovery index.
        index2 = client.get("/discovery")
        token3 = _csrf(index2.text)
        second = client.post(
            f"/discovery/results/{opp_id}/promote",
            data={
                "csrf_token": token3,
                "expected_version": int(version_match.group(1)),
            },
            follow_redirects=False,
        )
        # Idempotent promote returns 303; stale version → 409.
        assert second.status_code in (303, 409)
        final = client.get(f"/discovery/results/{opp_id}")
        assert "promoted" in final.text
        assert "Одобрить мониторинг" not in final.text
        assert "Одобрить в Источниках" in final.text
        assert "/sources#source-" in final.text
        assert 'href="/sources' in final.text


@pytest.mark.asyncio
async def test_discovery_inaccessible_gateway_state(discovery_ui_env) -> None:
    _paths, _seed, app = discovery_ui_env
    app.state.telegram_credentials_present = False
    with TestClient(app) as client:
        page = client.get("/discovery")
        assert page.status_code == 200
        assert "credentials_missing" in page.text
        assert "disabled" in page.text
        assert ZERO_STARS_LABEL in page.text
        assert "allow_paid" not in page.text.lower()
