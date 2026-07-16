"""Notification worker — fake Bot API, retries, uncertain delivery, shadow, HTML escape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1
from telegram_lead_discovery.infrastructure.paths import ensure_app_directories, resolve_app_paths
from telegram_lead_discovery.notifications.worker import (
    deliver_one,
    escape_html,
    process_one,
    requeue_dead,
)
from telegram_lead_discovery.settings.service import seed_defaults, update_setting
from telegram_lead_discovery.storage.db import dispose_engine, init_engine
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import NotificationOutbox
from telegram_lead_discovery.storage.outbox import enqueue_hot_lead, enqueue_outbox
from telegram_lead_discovery.storage.session import configure_session_factory, run_write


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True, "result": {"message_id": 99}}

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(
        self,
        responses: list[FakeResponse] | None = None,
        *,
        raise_timeout: bool = False,
    ) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict] = []
        self.raise_timeout = raise_timeout

    async def post(self, url: str, *, json: dict | None = None):
        self.calls.append({"url": url, "json": json})
        if self.raise_timeout:
            raise TimeoutError("timeout")
        if not self.responses:
            raise TimeoutError("no response")
        return self.responses.pop(0)


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("TG_NOTIFY_CHAT_ID", "-1001")
    paths = ensure_app_directories(resolve_app_paths())
    upgrade_head(paths.database_path)
    engine = await init_engine(paths.database_path)
    configure_session_factory(engine)

    async def _seed(session):
        await seed_defaults(session)
        await seed_ruleset_ru_mvp_1(session)
        await update_setting(
            session,
            key="notifications.delivery_mode",
            value="live",
            expected_settings_version=1,
        )
        row = NotificationOutbox(
            event_type="hot_lead",
            lead_id=1,
            incident_id=None,
            score_version=1,
            idempotency_key="hot_lead:1:1",
            state="queued",
            created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        )
        session.add(row)

    await run_write(_seed)
    yield paths
    await dispose_engine()


@pytest.mark.asyncio
async def test_notification_send_success(db_env) -> None:
    client = FakeClient([FakeResponse(200)])

    async def _run(session):
        return await deliver_one(session, client=client, now=datetime.now(UTC))

    ok = await run_write(_run)
    assert ok is True
    assert client.calls
    assert "sendMessage" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_notification_uncertain_goes_dead(db_env) -> None:
    client = FakeClient(raise_timeout=True)

    async def _run(session):
        return await process_one(session, client=client, now=datetime.now(UTC))

    delivery = await run_write(_run)
    assert delivery is not None
    assert delivery.error_code == "delivery_uncertain"

    async def _check(session):
        row = (await session.execute(select(NotificationOutbox))).scalar_one()
        return row.state

    assert await run_write(_check) == "dead"


@pytest.mark.asyncio
async def test_confirmed_error_retry_then_dead(db_env) -> None:
    created = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    for attempt in range(1, 5):
        err = FakeResponse(400, {"ok": False, "description": "Bad Request"})
        now = created + timedelta(minutes=attempt * 200)
        client = FakeClient([err])

        async def _attempt(session, client=client, clock=now):
            return await process_one(session, client=client, now=clock)

        delivery = await run_write(_attempt)
        assert delivery.status == "error_response"

        async def _state(session):
            row = (await session.execute(select(NotificationOutbox))).scalar_one()
            return row.state, row.available_at, row.automatic_attempt_count

        state, available_at, count = await run_write(_state)
        assert state == "retry_wait"
        assert count == attempt
        assert available_at is not None

    err = FakeResponse(400, {"ok": False, "description": "Bad Request"})

    async def _final_attempt(session):
        return await process_one(
            session,
            client=FakeClient([err]),
            now=created + timedelta(hours=3),
        )

    delivery = await run_write(_final_attempt)
    assert delivery.status == "error_response"

    async def _final(session):
        row = (await session.execute(select(NotificationOutbox))).scalar_one()
        return row.state, row.automatic_attempt_count

    state, count = await run_write(_final)
    assert state == "dead"
    assert count == 5


@pytest.mark.asyncio
async def test_shadow_mode_process_one_no_bot_api(db_env) -> None:
    async def _shadow(session):
        await update_setting(
            session,
            key="notifications.delivery_mode",
            value="shadow",
            expected_settings_version=2,
        )
        client = FakeClient([FakeResponse(200)])
        result = await process_one(session, client=client, now=datetime.now(UTC))
        return result, len(client.calls)

    result, calls = await run_write(_shadow)
    assert result is None
    assert calls == 0


@pytest.mark.asyncio
async def test_warm_lead_never_creates_outbox(db_env) -> None:
    async def _warm(session):
        return await enqueue_outbox(
            session,
            event_type="warm_lead",
            idempotency_key="warm_lead:9:1",
            lead_id=9,
            score_version=1,
            delivery_mode="live",
        )

    result = await run_write(_warm)
    assert result.inserted is False
    assert result.skipped_reason == "undeliverable_event_type"

    async def _count(session):
        return (
            await session.execute(
                select(func.count()).select_from(NotificationOutbox).where(
                    NotificationOutbox.idempotency_key == "warm_lead:9:1"
                )
            )
        ).scalar_one()

    assert await run_write(_count) == 0


@pytest.mark.asyncio
async def test_escape_html_prevents_injection_in_payload(db_env) -> None:
    assert "&lt;script&gt;" in escape_html("<script>alert(1)</script>")
    assert escape_html("a & b") == "a &amp; b"

    async def _inject(session):
        existing = list((await session.execute(select(NotificationOutbox))).scalars())
        for row in existing:
            row.state = "sent"
        row = NotificationOutbox(
            event_type="critical.system_event",
            lead_id=None,
            incident_id="<img src=x onerror=alert(1)>",
            score_version=None,
            idempotency_key="critical:inject",
            state="queued",
        )
        session.add(row)
        await session.flush()
        client = FakeClient([FakeResponse(200)])
        await process_one(session, client=client, now=datetime.now(UTC))
        return client.calls[0]["json"]["text"]

    text = await run_write(_inject)
    assert "<img" not in text
    assert "&lt;img" in text


@pytest.mark.asyncio
async def test_idempotency_key_crash_replay_one_outbox(db_env) -> None:
    async def _replay(session):
        first = await enqueue_hot_lead(session, lead_id=42, score_version=7)
        second = await enqueue_hot_lead(session, lead_id=42, score_version=7)
        rows = list(
            (
                await session.execute(
                    select(NotificationOutbox).where(
                        NotificationOutbox.idempotency_key == "hot_lead:42:7"
                    )
                )
            ).scalars()
        )
        return first, second, rows

    first, second, rows = await run_write(_replay)
    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_critical_incident_without_lead_id(db_env) -> None:
    async def _crit(session):
        existing = list((await session.execute(select(NotificationOutbox))).scalars())
        for row in existing:
            row.state = "sent"
        row = NotificationOutbox(
            event_type="critical.system_event",
            lead_id=None,
            incident_id="inc-1",
            score_version=None,
            idempotency_key="critical.system_event:inc-1",
            state="queued",
        )
        session.add(row)
        await session.flush()
        client = FakeClient([FakeResponse(200)])
        ok = await deliver_one(session, client=client, now=datetime.now(UTC))
        return ok, client.calls[0]["json"]["text"]

    ok, text = await run_write(_crit)
    assert ok is True
    assert "inc-1" in text
    assert "Critical" in text


@pytest.mark.asyncio
async def test_manual_requeue_dead_once(db_env) -> None:
    async def _dead_then_requeue(session):
        row = (await session.execute(select(NotificationOutbox))).scalar_one()
        row.state = "dead"
        row.automatic_attempt_count = 5
        await session.flush()
        requeued = await requeue_dead(session, row.id)
        return requeued.state, requeued.automatic_attempt_count, requeued.manual_retry_count

    state, attempts, manual = await run_write(_dead_then_requeue)
    assert state == "queued"
    assert attempts == 0
    assert manual == 1

    async def _second(session):
        row = (await session.execute(select(NotificationOutbox))).scalar_one()
        with pytest.raises(ValueError, match="outbox_not_dead"):
            await requeue_dead(session, row.id)

    await run_write(_second)
