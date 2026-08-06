from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from telegram_lead_discovery.collector.fake import FakeTelegramGateway, make_hit, make_source
from telegram_lead_discovery.collector.ports import TelegramMessageDTO
from telegram_lead_discovery.infrastructure.paths import database_path, ensure_directories
from telegram_lead_discovery.source_discovery.keyword_run import (
    cancel_keyword_discovery_run,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    create_keyword_discovery_profile,
)
from telegram_lead_discovery.source_discovery.worker import (
    claim_and_process_keyword_job,
    process_keyword_discovery_job,
)
from telegram_lead_discovery.source_discovery.worker_parts import verification_resume
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _parked_queries,
    _restore_linked_parents,
)
from telegram_lead_discovery.storage.db import dispose_engine, init_engine, session_scope
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    DiscoveryTerminalOutcome,
    Job,
    PresentedKeywordSource,
    RuleSetVersion,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
)


@pytest.fixture
async def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    path = database_path()
    upgrade_head(path)
    await init_engine(path)
    yield path
    await dispose_engine()


async def _start(session, name: str):
    profile = await create_keyword_discovery_profile(
        session,
        name=name,
        post_queries=["нужен сайт"],
        directory_queries=["предприниматели"],
        source_scope="groups",
    )
    return await start_keyword_discovery_run(session, profile_id=profile.profile.id)


def _active_messages(source_id: int, *, now: datetime) -> list[TelegramMessageDTO]:
    messages: list[TelegramMessageDTO] = []
    for index in range(100):
        text = (
            f"Нужен сайт для бизнеса, задача номер {index}"
            if index < 3
            else f"Обсуждаем работу бизнеса, сообщение {index}"
        )
        messages.append(
            TelegramMessageDTO(
                schema_version=2,
                source_id=0,
                telegram_message_id=10_000 - index,
                published_at=now - timedelta(days=index % 10, minutes=index),
                text=text,
                telegram_peer_id=source_id,
                author_peer_id=1_000 + index % 20,
                author_kind="user",
                permalink=f"https://t.me/client_chat/{10_000 - index}",
            )
        )
    return messages


def _gateway(source_id: int, messages: list[TelegramMessageDTO]) -> FakeTelegramGateway:
    gateway = FakeTelegramGateway()
    source = make_source(
        telegram_id=source_id,
        username="client_chat",
        source_type="megagroup",
        title="Предприниматели — активный чат",
    )
    gateway.register_source(source.username, source)
    gateway.set_directory_results([source])
    gateway.set_global_hits([])
    gateway.set_quota(free_slot_available=True)
    gateway.register_messages_for_peer(source_id, messages)
    return gateway


@pytest.mark.asyncio
async def test_quality_chat_passes_and_is_permanently_suppressed(db_env) -> None:
    source_id = 71_001
    gateway = _gateway(source_id, _active_messages(source_id, now=datetime.now(UTC)))
    async with session_scope() as session:
        started = await _start(session, "active-quality")
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_keyword_job(session, gateway)
        assert result and result["outcome"] == "succeeded"

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        snapshot = (
            await session.execute(
                select(SourceOpportunitySnapshot).where(SourceOpportunitySnapshot.run_id == run_id)
            )
        ).scalar_one()
        assert run and run.gate_status == "pass"
        assert snapshot.truth_status == "quality"
        assert snapshot.activity_message_count == 100
        assert snapshot.activity_active_day_count == 10
        assert snapshot.activity_distinct_author_count == 20
        assert snapshot.client_request_count == 3
        assert snapshot.client_request_author_count == 3
        assert snapshot.verification_stop_reason == "quality_reached"
        qualified_evidence = list(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence).where(
                        SourceDiscoveryEvidence.run_id == run_id,
                        SourceDiscoveryEvidence.is_qualified.is_(True),
                    )
                )
            ).scalars()
        )
        assert len(qualified_evidence) == 3
        assert len({row.author_key for row in qualified_evidence}) == 3
        assert await session.scalar(select(func.count()).select_from(DiscoveryTerminalOutcome)) == 1
        assert await session.scalar(select(func.count()).select_from(PresentedKeywordSource)) == 1

    history_calls = len(gateway.history_calls)
    async with session_scope() as session:
        second = await _start(session, "active-quality-second")
        second_run_id = second.run.id
    async with session_scope() as session:
        await claim_and_process_keyword_job(session, gateway)
    assert len(gateway.history_calls) == history_calls
    async with session_scope() as session:
        second_run = await session.get(DiscoveryRun, second_run_id)
        counters = json.loads(second_run.counters_json or "{}")
        assert counters["presented_suppressed"] == 1
        assert (
            not (
                await session.execute(
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == second_run_id
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_flood_is_nonterminal_then_cancel_suppresses_inconclusive(db_env) -> None:
    source_id = 71_002
    gateway = _gateway(source_id, _active_messages(source_id, now=datetime.now(UTC)))
    gateway.set_flood_wait(datetime.now(UTC) + timedelta(minutes=5), "iter_history")
    async with session_scope() as session:
        started = await _start(session, "active-cancel")
        run_id, job_id = started.run.id, started.job.id

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_keyword_discovery_job(session, job, gateway)
        assert result["outcome"] == "retry_wait"
    async with session_scope() as session:
        assert await session.scalar(select(func.count()).select_from(DiscoveryTerminalOutcome)) == 0
        assert await session.scalar(select(func.count()).select_from(PresentedKeywordSource)) == 0
        run = await session.get(DiscoveryRun, run_id)
        await cancel_keyword_discovery_run(session, run_id=run_id, expected_version=run.version)

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        result = await process_keyword_discovery_job(session, job, gateway)
        assert result["outcome"] == "cancelled"
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        outcome = (await session.execute(select(DiscoveryTerminalOutcome))).scalar_one()
        snapshot = (await session.execute(select(SourceOpportunitySnapshot))).scalar_one()
        assert run.run_termination_reason == "cancelled"
        assert run.gate_status == "inconclusive"
        counters = json.loads(run.counters_json)
        assert counters["inconclusive_sources"] == 1
        assert counters["presented_total"] == 1
        assert counters["countable_client_requests"] == 0
        assert counters["distinct_client_authors"] == 0
        assert outcome.truth_status == "inconclusive"
        assert outcome.verification_stop_reason == "cancelled"
        assert snapshot.truth_status == "inconclusive"
        assert await session.scalar(select(func.count()).select_from(PresentedKeywordSource)) == 1


@pytest.mark.asyncio
async def test_history_detection_uses_run_pinned_ruleset(db_env) -> None:
    source_id = 71_003
    messages = _active_messages(source_id, now=datetime.now(UTC))
    messages[0] = replace(messages[0], text="вакансия разработчика сайта")
    gateway = _gateway(source_id, messages)
    gateway.set_global_hits(
        [
            make_hit(
                source=make_source(
                    telegram_id=source_id,
                    username="client_chat",
                    source_type="megagroup",
                    title="Pinned acquisition",
                ),
                message_id=99_001,
                excerpt="вакансия разработчика сайта",
                published_at=datetime.now(UTC),
            )
        ]
    )
    async with session_scope() as session:
        started = await _start(session, "active-pinned-rules")
        pinned = (
            await session.execute(select(RuleSetVersion).where(RuleSetVersion.slug == "ru-mvp-3"))
        ).scalar_one()
        started.run.rule_set_version_id = pinned.id
        started.run.rule_set_checksum = pinned.checksum
        run_id = started.run.id
        pinned_checksum = pinned.checksum

    async with session_scope() as session:
        result = await claim_and_process_keyword_job(session, gateway)
        assert result and result["outcome"] == "succeeded"

    async with session_scope() as session:
        checksums = set(
            (
                await session.execute(
                    select(SourceDiscoveryEvidence.rule_set_checksum).where(
                        SourceDiscoveryEvidence.run_id == run_id
                    )
                )
            ).scalars()
        )
        assert checksums == {pinned_checksum}


@pytest.mark.asyncio
async def test_succeeded_linked_query_restores_candidate_after_restart(db_env) -> None:
    async with session_scope() as session:
        started = await _start(session, "linked-restart")
        session.add(
            DiscoveryRunQuery(
                run_id=started.run.id,
                ordinal=100,
                query_kind="linked_discussion",
                query_text="",
                source_telegram_id=88_001,
                state="succeeded",
                cursor_json=json.dumps(
                    {
                        "linked_discussion": {
                            "telegram_id": 88_002,
                            "username": "restored_clients",
                            "title": "Restored clients",
                            "source_type": "megagroup",
                            "public_url": "https://t.me/restored_clients",
                            "parent_telegram_id": 88_001,
                        }
                    }
                ),
            )
        )

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, started.run.id)
        ctx = SimpleNamespace(
            session=session,
            run=run,
            linked_parents={},
            directory_sources=[],
        )
        await _restore_linked_parents(ctx)
        assert ctx.linked_parents == {88_002: 88_001}
        assert [source.telegram_id for source in ctx.directory_sources] == [88_002]


@pytest.mark.asyncio
async def test_running_linked_query_is_resumable_after_crash(db_env) -> None:
    async with session_scope() as session:
        started = await _start(session, "linked-running-restart")
        query = DiscoveryRunQuery(
            run_id=started.run.id,
            ordinal=101,
            query_kind="linked_discussion",
            query_text="",
            source_telegram_id=89_001,
            state="running",
        )
        session.add(query)
        await session.flush()
        ctx = SimpleNamespace(session=session, run=started.run)
        parked = await _parked_queries(ctx, "linked_discussion")
        assert [row.id for row in parked] == [query.id]


@pytest.mark.asyncio
async def test_missing_qualified_evidence_cannot_produce_pass(
    db_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_capacity(_ctx, *, is_qualified: bool) -> bool:
        return not is_qualified

    monkeypatch.setattr(
        verification_resume,
        "_may_persist_evidence",
        no_capacity,
    )
    source_id = 71_004
    gateway = _gateway(source_id, _active_messages(source_id, now=datetime.now(UTC)))
    async with session_scope() as session:
        started = await _start(session, "qualified-evidence-required")
        run_id = started.run.id

    async with session_scope() as session:
        result = await claim_and_process_keyword_job(session, gateway)
        assert result and result["outcome"] == "failed"
        assert result["error"] == "evidence_capacity_invariant"

    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        verification_query = (
            await session.execute(
                select(DiscoveryRunQuery).where(
                    DiscoveryRunQuery.run_id == run_id,
                    DiscoveryRunQuery.query_kind == "source_verification",
                )
            )
        ).scalar_one()
        assert run and run.state == "failed"
        assert run.pool_exhausted is False
        assert run.run_termination_reason == "failed"
        assert verification_query.state == "failed"
        assert verification_query.error_code == "evidence_capacity_invariant"
        assert (
            not (
                await session.execute(
                    select(SourceOpportunitySnapshot).where(
                        SourceOpportunitySnapshot.run_id == run_id
                    )
                )
            )
            .scalars()
            .all()
        )
