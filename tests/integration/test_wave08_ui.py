"""Wave 08 — UI-019..024 route/HTML acceptance (AT-UI-019..024)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from telegram_lead_discovery.dashboard.app import create_app
from telegram_lead_discovery.dashboard.discovery_routes import (
    CONFIRM_RECONSIDER_SUPPRESS,
    ZERO_STARS_LABEL,
)
from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.profile_service import ensure_seed_keyword_profile
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    peer_canonical_key,
    upsert_dismiss_suppress,
)
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    DismissedKeywordSource,
    Job,
    SourceAlias,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token missing in HTML"
    return match.group(1)


@pytest.fixture
async def wave08_ui_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "hash-for-wave08")
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


async def _start_run(client: TestClient, profile_id: int) -> int:
    index = client.get("/discovery")
    token = _csrf(index.text)
    started = client.post(
        "/discovery/runs",
        data={"csrf_token": token, "profile_id": profile_id},
        follow_redirects=False,
    )
    assert started.status_code == 303
    return int(started.headers["location"].rsplit("/", 1)[-1])


@pytest.mark.asyncio
async def test_at_ui_025_default_shows_all_truth_buckets(wave08_ui_env) -> None:
    _paths, seed, app = wave08_ui_env
    with TestClient(app) as client:
        run_id = await _start_run(client, seed.profile.id)

        async def _seed_bands(session):
            session.add_all(
                [
                    SourceOpportunitySnapshot(
                        run_id=run_id,
                        source_telegram_id=8101,
                        username="w08_promising",
                        title="W08 Promising",
                        source_type="megagroup",
                        public_url="https://t.me/w08_promising",
                        score=80,
                        band="promising",
                        score_components_json='{"eligibility_reasons":["ok"]}',
                        discovery_channels_json='["global_message"]',
                        review_state="unreviewed",
                        version=1,
                    ),
                    SourceOpportunitySnapshot(
                        run_id=run_id,
                        source_telegram_id=8102,
                        username="w08_weak",
                        title="W08 Weak",
                        source_type="channel",
                        public_url="https://t.me/w08_weak",
                        score=5,
                        band="weak",
                        score_components_json="{}",
                        discovery_channels_json='["directory"]',
                        review_state="unreviewed",
                        version=1,
                    ),
                ]
            )

        await run_write(_seed_bands)
        detail = client.get(f"/discovery/runs/{run_id}")
        assert detail.status_code == 200
        default_frag = client.get(f"/discovery/runs/{run_id}/results-fragment")
        assert "W08 Promising" in default_frag.text
        assert "W08 Weak" in default_frag.text
        assert '<option value="all" selected>все (правда)</option>' in default_frag.text
        promising = client.get(
            f"/discovery/runs/{run_id}/results-fragment",
            params={"band": "promising"},
        )
        assert "W08 Promising" in promising.text
        assert "W08 Weak" not in promising.text
        weak = client.get(
            f"/discovery/runs/{run_id}/results-fragment", params={"band": "weak"}
        )
        assert "W08 Weak" in weak.text


@pytest.mark.asyncio
async def test_at_ui_020_funnel_counters_visible(wave08_ui_env) -> None:
    _paths, seed, app = wave08_ui_env
    with TestClient(app) as client:
        run_id = await _start_run(client, seed.profile.id)

        async def _counters(session):
            from telegram_lead_discovery.storage.models import DiscoveryRun

            run = await session.get(DiscoveryRun, run_id)
            assert run is not None
            run.counters_json = json.dumps(
                {
                    "acquired_total": 12,
                    "canonicalized_total": 10,
                    "registry_suppressed": 2,
                    "dismissed_suppressed": 1,
                    "cooldown_suppressed": 1,
                    "qualified_total": 4,
                    "presented_total": 3,
                    "novel_presented_total": 2,
                    "pool_exhausted": 1,
                    "pool_exhausted_reason_code": 0,
                    "novelty_ratio_bp": 6666,
                }
            )
            run.state = "succeeded"

        await run_write(_counters)
        page = client.get(f"/discovery/runs/{run_id}")
        assert page.status_code == 200
        assert "Воронка" in page.text or "funnel" in page.text.lower()
        assert "Acquired:" in page.text
        assert "Canonicalized:" in page.text
        assert "Presented:" in page.text
        assert "Novel:" in page.text
        assert "pool_exhausted" in page.text
        assert "provider_empty" in page.text
        assert "novelty_ratio" in page.text
        status = client.get(f"/discovery/runs/{run_id}/status-fragment")
        assert "6666" in status.text or "66.66%" in status.text


@pytest.mark.asyncio
async def test_at_ui_022_opportunity_card_fields(wave08_ui_env) -> None:
    _paths, seed, app = wave08_ui_env
    with TestClient(app) as client:
        run_id = await _start_run(client, seed.profile.id)

        async def _card(session):
            src = TelegramSource(
                telegram_id=8201,
                username_normalized="card_src",
                title="Card Src",
                source_type="channel",
                public_url="https://t.me/card_src",
                lifecycle_state="candidate",
            )
            session.add(src)
            await session.flush()
            session.add(
                SourceAlias(
                    source_id=src.id,
                    normalized_username="card_alias",
                )
            )
            snap = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=8201,
                username="card_src",
                title="Card Opp",
                source_type="channel",
                public_url="https://t.me/card_src",
                score=55,
                band="review",
                score_components_json=json.dumps(
                    {
                        "qualified": 3,
                        "regularity": 2,
                        "eligibility_reasons": ["needs_verification"],
                        "reason_codes": ["needs_verification"],
                    }
                ),
                discovery_channels_json='["directory","source_verification"]',
                review_state="unreviewed",
                qualified_count=3,
                excluded_count=1,
                sample_message_count=5,
                source_id=src.id,
                version=1,
            )
            session.add(snap)
            await session.flush()
            session.add(
                SourceDiscoveryEvidence(
                    run_id=run_id,
                    source_telegram_id=8201,
                    source_username="card_src",
                    source_title="Card Opp",
                    source_type="channel",
                    telegram_message_id=1,
                    published_at=datetime(2026, 7, 1, tzinfo=UTC),
                    permalink="https://t.me/card_src/1",
                    excerpt="нужен сайт",
                    normalized_hash="cardhash",
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

        opp_id = await run_write(_card)
        page = client.get(f"/discovery/results/{opp_id}")
        assert page.status_code == 200
        assert "Идентичность" in page.text
        assert "card_src" in page.text
        assert "card_alias" in page.text
        assert "peer:8201" in page.text
        assert "directory" in page.text
        assert "needs_verification" in page.text
        assert "Компоненты score" in page.text
        assert "нужен сайт" in page.text
        assert ZERO_STARS_LABEL in page.text
        assert "stars_amount" not in page.text.lower()
        assert "send-to-author" not in page.text.lower()


@pytest.mark.asyncio
async def test_at_ui_019_reconsider_suppress_requires_confirm(wave08_ui_env) -> None:
    _paths, seed, app = wave08_ui_env
    with TestClient(app) as client:
        run_id = await _start_run(client, seed.profile.id)

        async def _dismissed(session):
            snap = SourceOpportunitySnapshot(
                run_id=run_id,
                source_telegram_id=8301,
                username="supp_src",
                title="Supp Opp",
                source_type="channel",
                public_url="https://t.me/supp_src",
                score=40,
                band="review",
                score_components_json="{}",
                discovery_channels_json='["global_message"]',
                review_state="dismissed",
                dismiss_reason="hidden_by_operator",
                version=1,
            )
            session.add(snap)
            await session.flush()
            row = await upsert_dismiss_suppress(
                session,
                identity=SuppressIdentity(
                    canonical_key=peer_canonical_key(8301),
                    telegram_id=8301,
                    username_normalized="supp_src",
                ),
                reason="hidden_by_operator",
                origin_run_id=run_id,
                origin_opportunity_id=snap.id,
            )
            return snap.id, row.id, row.version

        opp_id, suppress_id, version = await run_write(_dismissed)
        page = client.get(f"/discovery/results/{opp_id}")
        assert page.status_code == 200
        assert "ReconsiderDismissSuppress" in page.text
        assert "ReconsiderSource" not in page.text or "отдельно" in page.text.lower()
        token = _csrf(page.text)

        blocked = client.post(
            f"/discovery/results/{opp_id}/reconsider-suppress",
            data={
                "csrf_token": token,
                "confirm": "",
                "suppress_id": suppress_id,
                "expected_version": version,
            },
            follow_redirects=False,
        )
        assert blocked.status_code == 400
        assert "confirm" in blocked.text.lower() or "подтвержд" in blocked.text.lower()

        async def _still_there(session):
            return await session.get(DismissedKeywordSource, suppress_id)

        assert await run_write(_still_there) is not None

        page2 = client.get(f"/discovery/results/{opp_id}")
        token2 = _csrf(page2.text)
        ok = client.post(
            f"/discovery/results/{opp_id}/reconsider-suppress",
            data={
                "csrf_token": token2,
                "confirm": CONFIRM_RECONSIDER_SUPPRESS,
                "suppress_id": suppress_id,
                "expected_version": version,
                "note": "wave08",
            },
            follow_redirects=False,
        )
        assert ok.status_code == 303
        assert await run_write(_still_there) is None


@pytest.mark.asyncio
async def test_at_ui_023_lifecycle_actions_matrix(wave08_ui_env) -> None:
    _paths, _seed, app = wave08_ui_env

    async def _sources(session):
        rows = [
            TelegramSource(
                telegram_id=8401,
                username_normalized="cand_src",
                title="Candidate",
                source_type="channel",
                lifecycle_state="candidate",
            ),
            TelegramSource(
                telegram_id=8402,
                username_normalized="rej_src",
                title="Rejected",
                source_type="channel",
                lifecycle_state="rejected",
            ),
            TelegramSource(
                telegram_id=8403,
                username_normalized="mon_src",
                title="Monitoring",
                source_type="channel",
                lifecycle_state="monitoring",
            ),
            TelegramSource(
                telegram_id=8404,
                username_normalized="pause_src",
                title="Paused",
                source_type="channel",
                lifecycle_state="paused",
            ),
        ]
        session.add_all(rows)
        await session.flush()
        return {r.username_normalized: r.id for r in rows}

    ids = await run_write(_sources)
    with TestClient(app) as client:
        page = client.get("/sources")
        assert page.status_code == 200
        assert "Отклонить" in page.text
        assert "ReconsiderSource" in page.text
        assert "Пауза" in page.text
        assert "Возобновить" in page.text
        assert "Отключить" in page.text
        assert "send-to-author" not in page.text.lower()
        assert "stars" not in page.text.lower() or ZERO_STARS_LABEL.split()[0] not in page.text
        # stars paid controls must not appear
        assert "allow_paid" not in page.text.lower()
        assert 'name="stars' not in page.text.lower()

        token = _csrf(page.text)
        reject = client.post(
            f"/sources/{ids['cand_src']}/reject",
            data={
                "csrf_token": token,
                "reason_code": "off_topic",
            },
            follow_redirects=False,
        )
        assert reject.status_code == 303

        page2 = client.get("/sources")
        token2 = _csrf(page2.text)
        recon = client.post(
            f"/sources/{ids['rej_src']}/reconsider",
            data={"csrf_token": token2},
            follow_redirects=False,
        )
        assert recon.status_code == 303

        page3 = client.get("/sources")
        token3 = _csrf(page3.text)
        pause = client.post(
            f"/sources/{ids['mon_src']}/pause",
            data={"csrf_token": token3},
            follow_redirects=False,
        )
        assert pause.status_code == 303

        page4 = client.get("/sources")
        token4 = _csrf(page4.text)
        resume = client.post(
            f"/sources/{ids['pause_src']}/resume",
            data={"csrf_token": token4},
            follow_redirects=False,
        )
        assert resume.status_code == 303


@pytest.mark.asyncio
async def test_at_ui_024_monitoring_coverage(wave08_ui_env) -> None:
    _paths, _seed, app = wave08_ui_env

    async def _mon(session):
        src = TelegramSource(
            telegram_id=8501,
            username_normalized="cov_src",
            title="Coverage Src",
            source_type="channel",
            lifecycle_state="monitoring",
            access_error_code=None,
        )
        session.add(src)
        await session.flush()
        session.add(
            CollectorCheckpoint(
                source_id=src.id,
                last_committed_message_id=42,
                last_committed_published_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        session.add(
            Job(
                job_type="initial_backfill",
                dedupe_key=f"backfill:{src.id}",
                state="queued",
                payload_json=json.dumps({"source_id": src.id}),
                last_error_code="flood_wait",
            )
        )
        await session.flush()
        return src.id

    src_id = await run_write(_mon)
    with TestClient(app) as client:
        page = client.get("/sources/monitoring")
        assert page.status_code == 200
        assert "Покрытие мониторинга" in page.text
        assert "cov_src" in page.text
        assert "42" in page.text
        assert "flood_wait" in page.text
        assert str(src_id) in page.text
        sources = client.get("/sources")
        assert "monitoring-coverage" in sources.text or "Покрытие мониторинга" in sources.text


@pytest.mark.asyncio
async def test_wave08_health_named_loops_and_inbox_rule_pin(wave08_ui_env) -> None:
    _paths, _seed, app = wave08_ui_env
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        for name in (
            "discovery_claim",
            "collector_jobs",
            "live_updates",
            "processing_claim",
            "notification_outbox",
            "reconciliation",
            "health_watchdog",
        ):
            assert name in health.text

        home = client.get("/")
        assert home.status_code == 200
        assert "Active rules:" in home.text or "checksum=" in home.text
        assert "ru-mvp" in home.text or "checksum=" in home.text
