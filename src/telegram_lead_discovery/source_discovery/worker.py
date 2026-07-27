"""Keyword discovery persisted worker (SRC-019..029, plan §12).

Drives phases B–I for ``job_type=keyword_discovery``. Persists only scouting
evidence / opportunity snapshots — never TelegramMessage, Lead, outbox, or
checkpoint (D-052). FloodWait and transient errors use Job.retry_wait; the
worker never long-sleeps in the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
    GlobalSearchRequest,
    PublicPostSearchRequest,
    SearchCursor,
    SourceMessageSearchRequest,
    SourceRef,
    SourceSnapshot,
    TelegramGateway,
)
from telegram_lead_discovery.observability.discovery import (
    log_query_progress,
    log_run_finished,
    note_flood_wait,
    note_quota_skipped,
    note_run_recovered,
    note_session_fatal,
    note_transient_error,
    record_qualified_evidence,
    record_query_total,
    record_run_duration_seconds,
    record_run_total,
    record_score,
    record_search_hits,
    record_unique_sources,
    record_verified_sources,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    JOB_TYPE_KEYWORD_DISCOVERY,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    MAX_DEEP_VERIFICATION_SOURCES,
    MAX_EVIDENCE_PER_RUN,
    MAX_MESSAGES_PER_SOURCE,
    AnnotatedSearchHit,
    DismissedKeywordSourceEntry,
    DismissedKeywordSourceIndex,
    EvidenceRecord,
    OpportunitySnapshotRecord,
    RegistrySourceEntry,
    SourceRegistryIndex,
    aggregate_search_hits,
    build_opportunity_from_evidence,
    build_preliminary_candidates,
    is_registry_suppressed,
    linked_discussion_opportunity,
    registry_telegram_ids,
    resolve_dismissed_identity,
    resolve_source_identity,
    select_sources_for_deep_verification,
)
from telegram_lead_discovery.source_discovery.profile_service import version_as_normalized
from telegram_lead_discovery.storage.jobs import (
    HEARTBEAT_SECONDS,
    LEASE_SECONDS,
    claim_job,
    heartbeat_job,
    recover_stale_jobs,
)
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    DismissedKeywordSource,
    Job,
    KeywordDiscoveryProfileVersion,
    SourceAlias,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)

GLOBAL_PAGE_SIZE = 50
GLOBAL_MAX_PAGES = 2
DIRECTORY_PEER_LIMIT = 20
DEEP_QUERIES_PER_SOURCE = 5
TRANSIENT_RETRY_DELAYS_S = (30, 120, 600)
MAX_TRANSIENT_ATTEMPTS = 3

# Re-export lease constants so callers/tests bind to the same job-store values.
assert LEASE_SECONDS == 300
assert HEARTBEAT_SECONDS == 60


class _CancelRequested(Exception):
    """Internal control: operator cancel observed between network calls."""


class _FloodWaitControl(Exception):
    def __init__(self, until: datetime, query: DiscoveryRunQuery) -> None:
        self.until = until
        self.query = query
        super().__init__(until.isoformat())


class _SessionFatal(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class _WorkerContext:
    session: AsyncSession
    gateway: TelegramGateway
    job: Job
    run: DiscoveryRun
    profile_version: KeywordDiscoveryProfileVersion
    post_queries: tuple[str, ...]
    directory_queries: tuple[str, ...]
    registry: SourceRegistryIndex
    dismissed: DismissedKeywordSourceIndex
    directory_sources: list[SourceSnapshot]
    linked_parents: dict[int, int]
    last_heartbeat_at: datetime
    public_posts_quota_exhausted: bool = False
    registry_suppressed_ids: set[int] = field(default_factory=set)
    dismissed_suppressed_ids: set[int] = field(default_factory=set)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _loads_counters(raw: str | None) -> dict[str, int]:
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int | float)}


def _dumps_counters(counters: dict[str, int]) -> str:
    return json.dumps(counters, ensure_ascii=False)


def _cursor_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_cursor(query: DiscoveryRunQuery, payload: dict[str, Any]) -> None:
    query.cursor_json = json.dumps(payload, ensure_ascii=False)


def _search_cursor_from_payload(payload: dict[str, Any]) -> SearchCursor | None:
    token = payload.get("token")
    if token is None or token == "":
        return None
    return SearchCursor(schema_version=1, token=str(token))


def _transient_delay_seconds(attempt: int) -> int:
    """attempt is 1-based failed attempt count before scheduling next wait."""
    idx = min(max(attempt, 1), len(TRANSIENT_RETRY_DELAYS_S)) - 1
    return TRANSIENT_RETRY_DELAYS_S[idx]


async def process_keyword_discovery_job(
    session: AsyncSession,
    job: Job,
    gateway: TelegramGateway,
) -> dict[str, Any]:
    """Execute one claimed ``keyword_discovery`` job to a wait or terminal state."""
    if job.job_type != JOB_TYPE_KEYWORD_DISCOVERY:
        raise ValueError(f"unexpected_job_type:{job.job_type}")

    payload = json.loads(job.payload_json or "{}")
    run_id = int(payload["run_id"])
    run = await session.get(DiscoveryRun, run_id)
    if run is None or run.run_type != "keyword_scouting":
        job.state = "failed"
        job.last_error_code = "run_not_found"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "failed", "error": "run_not_found"}

    if run.state in ("succeeded", "partial", "failed", "cancelled"):
        job.state = "succeeded" if run.state != "failed" else "failed"
        if run.state == "cancelled":
            job.state = "cancelled"
        job.updated_at = _utcnow()
        await session.flush()
        return {"outcome": "already_terminal", "run_state": run.state}

    if run.profile_version_id is None:
        return await _fail_run(session, job, run, "profile_version_missing")

    version_row = await session.get(KeywordDiscoveryProfileVersion, run.profile_version_id)
    if version_row is None:
        return await _fail_run(session, job, run, "profile_version_missing")

    normalized = version_as_normalized(version_row)
    registry = await _load_registry(session)
    dismissed = await _load_dismissed_sources(session)
    now = _utcnow()
    if run.state in ("queued", "retry_wait_flood", "cancelling"):
        if run.state != "cancelling":
            run.state = "running"
        if run.started_at is None:
            run.started_at = now
    run.phase = run.phase or "B"
    await session.flush()

    ctx = _WorkerContext(
        session=session,
        gateway=gateway,
        job=job,
        run=run,
        profile_version=version_row,
        post_queries=normalized.post_queries,
        directory_queries=normalized.directory_queries,
        registry=registry,
        dismissed=dismissed,
        directory_sources=[],
        linked_parents={},
        last_heartbeat_at=now,
    )

    try:
        await _check_cancel(ctx)
        await _run_seed_queries(ctx)
        await _check_cancel(ctx)
        await _phase_linked_discussions(ctx)
        await _check_cancel(ctx)
        await _phase_deep_verification(ctx)
        await _check_cancel(ctx)
        await _phase_finalize_opportunities(ctx)
        return await _finish_run(ctx)
    except _CancelRequested:
        return await _mark_cancelled(ctx)
    except _FloodWaitControl as exc:
        return await _park_flood_wait(ctx, exc)
    except _SessionFatal as exc:
        note_session_fatal(code=exc.code)
        return await _fail_run(session, job, run, exc.code)


async def claim_and_process_keyword_job(
    session: AsyncSession,
    gateway: TelegramGateway,
    *,
    owner: str = "keyword-discovery-worker",
) -> dict[str, Any] | None:
    """Recover stale leases, claim one keyword job, process it."""
    await recover_stale_jobs(session)
    job = await claim_job(
        session,
        job_types=[JOB_TYPE_KEYWORD_DISCOVERY],
        owner=owner,
    )
    if job is None:
        return None
    return await process_keyword_discovery_job(session, job, gateway)


# Idle poll between empty claims. FloodWait jobs wake via Job.available_at — no long sleep.
CLAIM_LOOP_IDLE_SECONDS = 2.0
CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS = 30.0

_log = logging.getLogger("tld.source_discovery.worker")


class KeywordDiscoveryClaimLoop:
    """Asyncio claim loop for ``keyword_discovery`` jobs (INF-021).

    Not a FastAPI BackgroundTask — started as ``asyncio.create_task`` by runtime.
    On stop: finish the current short claim/process cycle when possible; leave any
    in-flight lease for ``recover_stale_jobs`` if the wait times out.
    """

    def __init__(
        self,
        gateway: TelegramGateway,
        *,
        idle_seconds: float = CLAIM_LOOP_IDLE_SECONDS,
        owner: str = "keyword-discovery-worker",
        shutdown_timeout_seconds: float = CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._idle_seconds = idle_seconds
        self._owner = owner
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="keyword-discovery-claim-loop",
        )
        return self._task

    async def stop(self) -> None:
        """Stop accepting new claims; await current short op up to timeout."""
        self._stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=self._shutdown_timeout_seconds)
        except TimeoutError:
            _log.warning(
                "keyword discovery claim loop shutdown timed out; "
                "leaving lease for recover_stale_jobs"
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    async def _run(self) -> None:
        from telegram_lead_discovery.storage.db import session_scope

        while not self._stop.is_set():
            claimed = False
            try:
                async with session_scope() as session:
                    outcome = await claim_and_process_keyword_job(
                        session,
                        self._gateway,
                        owner=self._owner,
                    )
                    claimed = outcome is not None
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — loop must not die on one job failure
                _log.exception("keyword discovery claim/process failed")
                claimed = True  # brief backoff via idle wait below

            if self._stop.is_set():
                break
            if claimed:
                # Yield to event loop before claiming next job.
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._idle_seconds)
                break
            except TimeoutError:
                continue


async def _load_registry(session: AsyncSession) -> SourceRegistryIndex:
    sources = list((await session.execute(select(TelegramSource))).scalars().all())
    aliases = list((await session.execute(select(SourceAlias))).scalars().all())
    alias_by_source: dict[int, list[str]] = {}
    for alias in aliases:
        alias_by_source.setdefault(alias.source_id, []).append(alias.normalized_username)
    entries = [
        RegistrySourceEntry(
            source_id=src.id,
            telegram_id=src.telegram_id,
            username_normalized=src.username_normalized,
            aliases=tuple(alias_by_source.get(src.id, ())),
        )
        for src in sources
    ]
    return SourceRegistryIndex.from_entries(entries)


async def _load_dismissed_sources(session: AsyncSession) -> DismissedKeywordSourceIndex:
    rows = list((await session.execute(select(DismissedKeywordSource))).scalars().all())
    entries: list[DismissedKeywordSourceEntry] = []
    for row in rows:
        aliases: tuple[str, ...]
        try:
            raw = json.loads(row.aliases_json or "[]")
            aliases = tuple(str(item) for item in raw if isinstance(item, str))
        except json.JSONDecodeError:
            aliases = ()
        entries.append(
            DismissedKeywordSourceEntry(
                telegram_id=row.source_telegram_id,
                username_normalized=row.username_normalized,
                aliases=aliases,
            )
        )
    return DismissedKeywordSourceIndex.from_entries(entries)


def _dismissed_canonical_id(
    ctx: _WorkerContext, *, telegram_id: int, username: str | None
) -> int | None:
    match = resolve_dismissed_identity(
        telegram_id=telegram_id,
        username=username,
        dismissed=ctx.dismissed,
    )
    return None if match is None else match.canonical_telegram_id


async def _check_cancel(ctx: _WorkerContext) -> None:
    await ctx.session.refresh(ctx.job)
    if ctx.job.cancel_requested_at is not None:
        ctx.run.state = "cancelling"
        await ctx.session.flush()
        raise _CancelRequested()
    await ctx.session.refresh(ctx.run)
    if ctx.run.state == "cancelling":
        raise _CancelRequested()


async def _commit_before_network(ctx: _WorkerContext) -> None:
    """End the current SQLite transaction before Telegram I/O (plan §7)."""
    await ctx.session.commit()


async def _maybe_heartbeat(ctx: _WorkerContext) -> None:
    now = _utcnow()
    if (now - ctx.last_heartbeat_at).total_seconds() >= HEARTBEAT_SECONDS:
        await heartbeat_job(ctx.session, ctx.job)
        ctx.last_heartbeat_at = now


async def _run_seed_queries(ctx: _WorkerContext) -> None:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind.in_(
                ("global_message", "directory", "public_posts")
            ),
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
    )
    queries = list(result.scalars().all())
    for query in queries:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if query.state in (
            "succeeded",
            "failed",
            "cancelled",
            "quota_skipped",
            "budget_skipped",
        ):
            continue
        if query.state == "retry_wait" and query.available_at is not None:
            if _ensure_utc(query.available_at) > _utcnow():
                # Still waiting — re-park job until query.available_at.
                raise _FloodWaitControl(_ensure_utc(query.available_at), query)
            query.state = "running"

        if (
            query.query_kind == "public_posts"
            and ctx.public_posts_quota_exhausted
            and query.state in ("queued", "running", "retry_wait")
        ):
            await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            continue

        if query.query_kind == "global_message":
            ctx.run.phase = "B"
            await _execute_global_query(ctx, query)
        elif query.query_kind == "directory":
            ctx.run.phase = "C"
            await _execute_directory_query(ctx, query)
        elif query.query_kind == "public_posts":
            ctx.run.phase = "D"
            await _execute_public_posts_query(ctx, query)
        await ctx.session.flush()


async def _execute_global_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    payload = _cursor_payload(query.cursor_json)
    pages_done = int(payload.get("pages_done", 0))
    cursor = _search_cursor_from_payload(payload)
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()

    groups_only = query.scope == "groups"
    broadcasts_only = query.scope == "channels"

    while pages_done < GLOBAL_MAX_PAGES:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if await _evidence_count(ctx) >= MAX_EVIDENCE_PER_RUN:
            await _mark_query_terminal(query, "budget_skipped", error_code="evidence_cap")
            await _bump_counter(ctx, "budget_skipped", 1)
            return

        request = GlobalSearchRequest(
            schema_version=1,
            query=query.query_text,
            groups_only=groups_only,
            broadcasts_only=broadcasts_only,
            limit=GLOBAL_PAGE_SIZE,
            cursor=cursor,
        )
        try:
            await _commit_before_network(ctx)
            page = await ctx.gateway.search_global(request)
        except GatewayFloodWait as exc:
            _save_cursor(
                query,
                {"token": cursor.token if cursor else "", "pages_done": pages_done},
            )
            raise _FloodWaitControl(exc.until, query) from exc
        except GatewayUnauthorized as exc:
            raise _SessionFatal("unauthorized") from exc
        except GatewayFrozen as exc:
            raise _SessionFatal("frozen") from exc
        except GatewayInvalidSearchQuery:
            await _mark_query_terminal(query, "failed", error_code="invalid_query")
            await _bump_counter(ctx, "failed_queries", 1)
            return
        except GatewayTransientError as exc:
            if await _handle_transient(ctx, query, "transient_error"):
                raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
            return
        except GatewayPermanentError:
            await _mark_query_terminal(query, "failed", error_code="permanent_error")
            await _bump_counter(ctx, "failed_queries", 1)
            return

        query.request_count += 1
        # Clear transient streak after a successful page.
        payload = _cursor_payload(query.cursor_json)
        payload.pop("transient_attempts", None)

        annotated = [
            AnnotatedSearchHit(
                hit=hit,
                query_ordinal=query.ordinal,
                discovery_channel="global_message",
            )
            for hit in page.hits
        ]
        await _persist_hits(ctx, annotated)
        query.result_count += len(page.hits)
        pages_done += 1
        next_token = page.next_cursor.token if page.next_cursor else ""
        _save_cursor(
            query,
            {"token": next_token, "pages_done": pages_done},
        )
        await ctx.session.flush()
        cursor = page.next_cursor
        if cursor is None or not page.hits:
            break

    await _mark_query_terminal(query, "succeeded")


async def _execute_directory_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()
    await _check_cancel(ctx)
    request = DirectorySearchRequest(
        schema_version=1,
        query=query.query_text,
        limit=DIRECTORY_PEER_LIMIT,
    )
    try:
        await _commit_before_network(ctx)
        peers = await ctx.gateway.search_public_sources(request)
    except GatewayFloodWait as exc:
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayInvalidSearchQuery:
        await _mark_query_terminal(query, "failed", error_code="invalid_query")
        await _bump_counter(ctx, "failed_queries", 1)
        return
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return
    except GatewayPermanentError:
        await _mark_query_terminal(query, "failed", error_code="permanent_error")
        await _bump_counter(ctx, "failed_queries", 1)
        return

    query.request_count += 1
    accepted = [
        p
        for p in peers
        if p.accessible and p.source_type in ("channel", "megagroup", "group") and p.username
    ]
    ctx.directory_sources.extend(accepted)
    query.result_count += len(accepted)
    await _mark_query_terminal(query, "succeeded")


async def _execute_public_posts_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    payload = _cursor_payload(query.cursor_json)
    pages_done = int(payload.get("pages_done", 0))
    cursor = _search_cursor_from_payload(payload)
    query.state = "running"
    if query.started_at is None:
        query.started_at = _utcnow()
    await ctx.session.flush()

    await _check_cancel(ctx)
    try:
        await _commit_before_network(ctx)
        quota = await ctx.gateway.check_public_post_search_quota(query.query_text)
    except GatewayFloodWait as exc:
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return

    ctx.run.quota_snapshot_json = json.dumps(
        {
            "free_slot_available": quota.free_slot_available,
            "premium_required": quota.premium_required,
            "stars_amount": quota.stars_amount,
        },
        ensure_ascii=False,
    )

    if quota.premium_required or (
        not quota.free_slot_available and quota.stars_amount > 0
    ):
        error = "premium_required" if quota.premium_required else "quota_exhausted"
        if not quota.free_slot_available:
            ctx.public_posts_quota_exhausted = True
        await _mark_query_terminal(query, "quota_skipped", error_code=error)
        await _bump_counter(ctx, "quota_skipped_queries", 1)
        return
    if not quota.free_slot_available:
        ctx.public_posts_quota_exhausted = True
        await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
        await _bump_counter(ctx, "quota_skipped_queries", 1)
        return

    while pages_done < GLOBAL_MAX_PAGES:
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        if await _evidence_count(ctx) >= MAX_EVIDENCE_PER_RUN:
            await _mark_query_terminal(query, "budget_skipped", error_code="evidence_cap")
            await _bump_counter(ctx, "budget_skipped", 1)
            return

        request = PublicPostSearchRequest(
            schema_version=1,
            query=query.query_text,
            limit=GLOBAL_PAGE_SIZE,
            cursor=cursor,
        )
        try:
            await _commit_before_network(ctx)
            page = await ctx.gateway.search_public_posts(request)
        except GatewayFloodWait as exc:
            _save_cursor(
                query,
                {"token": cursor.token if cursor else "", "pages_done": pages_done},
            )
            raise _FloodWaitControl(exc.until, query) from exc
        except GatewayPremiumRequired:
            ctx.public_posts_quota_exhausted = True
            await _mark_query_terminal(query, "quota_skipped", error_code="premium_required")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            return
        except GatewaySearchQuotaExhausted:
            ctx.public_posts_quota_exhausted = True
            await _mark_query_terminal(query, "quota_skipped", error_code="quota_exhausted")
            await _bump_counter(ctx, "quota_skipped_queries", 1)
            return
        except GatewayUnauthorized as exc:
            raise _SessionFatal("unauthorized") from exc
        except GatewayFrozen as exc:
            raise _SessionFatal("frozen") from exc
        except GatewayInvalidSearchQuery:
            await _mark_query_terminal(query, "failed", error_code="invalid_query")
            await _bump_counter(ctx, "failed_queries", 1)
            return
        except GatewayTransientError as exc:
            if await _handle_transient(ctx, query, "transient_error"):
                raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
            return
        except GatewayPermanentError:
            await _mark_query_terminal(query, "failed", error_code="permanent_error")
            await _bump_counter(ctx, "failed_queries", 1)
            return

        query.request_count += 1
        annotated = [
            AnnotatedSearchHit(
                hit=hit,
                query_ordinal=query.ordinal,
                discovery_channel="public_posts",
            )
            for hit in page.hits
        ]
        await _persist_hits(ctx, annotated)
        query.result_count += len(page.hits)
        pages_done += 1
        next_token = page.next_cursor.token if page.next_cursor else ""
        _save_cursor(query, {"token": next_token, "pages_done": pages_done})
        await ctx.session.flush()
        cursor = page.next_cursor
        if cursor is None or not page.hits:
            break

    await _mark_query_terminal(query, "succeeded")


async def _phase_linked_discussions(ctx: _WorkerContext) -> None:
    ctx.run.phase = "F"
    await ctx.session.flush()
    await _restore_linked_parents(ctx)
    known = await _source_ids_with_query_kind(ctx, "linked_discussion")
    channel_ids = await _channel_telegram_ids(ctx)
    next_ordinal = await _next_ordinal(ctx)

    for query in await _parked_queries(ctx, "linked_discussion"):
        await _resume_linked_query(ctx, query)

    for telegram_id in channel_ids:
        if telegram_id in known:
            continue
        await _check_cancel(ctx)
        await _maybe_heartbeat(ctx)
        query = DiscoveryRunQuery(
            run_id=ctx.run.id,
            ordinal=next_ordinal,
            query_kind="linked_discussion",
            query_text="",
            source_telegram_id=telegram_id,
            state="running",
            started_at=_utcnow(),
        )
        next_ordinal += 1
        ctx.session.add(query)
        await ctx.session.flush()
        await _resume_linked_query(ctx, query)


async def _resume_linked_query(ctx: _WorkerContext, query: DiscoveryRunQuery) -> None:
    telegram_id = query.source_telegram_id
    if telegram_id is None:
        await _mark_query_terminal(query, "failed", error_code="missing_source")
        return
    if (
        query.state == "retry_wait"
        and query.available_at
        and _ensure_utc(query.available_at) > _utcnow()
    ):
        raise _FloodWaitControl(_ensure_utc(query.available_at), query)
    query.state = "running"
    await ctx.session.flush()
    try:
        await _commit_before_network(ctx)
        discussion = await ctx.gateway.get_linked_discussion(
            SourceRef(schema_version=1, source_id=0, telegram_id=telegram_id)
        )
        query.request_count += 1
    except GatewayFloodWait as exc:
        query.state = "retry_wait"
        query.available_at = exc.until
        query.error_code = "flood_wait"
        await ctx.session.flush()
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewaySourceInaccessible:
        await _mark_query_terminal(query, "failed", error_code="source_inaccessible")
        return
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return

    if (
        discussion is None
        or not discussion.accessible
        or not discussion.username
        or discussion.source_type not in ("megagroup", "group")
    ):
        await _mark_query_terminal(query, "succeeded", error_code="no_public_linked")
        return

    ctx.linked_parents[discussion.telegram_id] = telegram_id
    identity = resolve_source_identity(
        telegram_id=discussion.telegram_id,
        username=discussion.username,
        registry=ctx.registry,
    )
    if is_registry_suppressed(identity, registry=ctx.registry):
        await _note_registry_suppressed(ctx, {identity.canonical_telegram_id})
        await _mark_query_terminal(query, "succeeded", error_code="registry_suppressed")
        return
    dismissed_match = resolve_dismissed_identity(
        telegram_id=identity.canonical_telegram_id,
        username=identity.username_normalized or discussion.username,
        dismissed=ctx.dismissed,
    )
    if dismissed_match is not None:
        await _note_dismissed_suppressed(ctx, {dismissed_match.canonical_telegram_id})
        await _mark_query_terminal(query, "succeeded", error_code="dismissed_suppressed")
        return
    snap = linked_discussion_opportunity(
        run_id=ctx.run.id,
        parent_telegram_id=telegram_id,
        discussion=discussion,
        scored_at=_utcnow(),
        registry_source_id=identity.registry_source_id,
    )
    await _upsert_opportunity(ctx, snap)
    query.result_count = 1
    await _mark_query_terminal(query, "succeeded")


async def _phase_deep_verification(ctx: _WorkerContext) -> None:
    ctx.run.phase = "G"
    await ctx.session.flush()
    evidence_rows = await _load_evidence_records(ctx)
    candidates = build_preliminary_candidates(
        evidence_rows,
        directory_sources=ctx.directory_sources,
        directory_query_texts=ctx.directory_queries,
        linked_parent_ids=ctx.linked_parents,
        registry=ctx.registry,
        dismissed=ctx.dismissed,
    )
    # Count directory-only suppressed ids that never appeared in seed evidence.
    known = registry_telegram_ids(ctx.registry)
    dir_suppressed = {s.telegram_id for s in ctx.directory_sources if s.telegram_id in known}
    await _note_registry_suppressed(ctx, dir_suppressed)
    dir_dismissed = {
        matched_id
        for s in ctx.directory_sources
        if (
            matched_id := _dismissed_canonical_id(
                ctx,
                telegram_id=s.telegram_id,
                username=s.username,
            )
        )
        is not None
    }
    await _note_dismissed_suppressed(ctx, dir_dismissed)
    selected = select_sources_for_deep_verification(
        candidates,
        limit=MAX_DEEP_VERIFICATION_SOURCES,
    )
    record_verified_sources(len(selected))
    ctx.run.phase = "H"
    await ctx.session.flush()

    deep_queries = list(ctx.post_queries[:DEEP_QUERIES_PER_SOURCE])
    if not deep_queries:
        return
    done_keys = await _finished_verification_keys(ctx)
    next_ordinal = await _next_ordinal(ctx)
    now = _utcnow()
    published_after = now - timedelta(days=30)

    for query in await _parked_queries(ctx, "source_verification"):
        await _resume_source_verification(ctx, query, published_after)
        if query.source_telegram_id is not None:
            done_keys.add((query.source_telegram_id, query.query_text))

    for candidate in selected:
        for query_text in deep_queries:
            key = (candidate.telegram_id, query_text)
            if key in done_keys:
                continue
            await _check_cancel(ctx)
            await _maybe_heartbeat(ctx)
            if await _evidence_count(ctx) >= MAX_EVIDENCE_PER_RUN:
                return
            query = DiscoveryRunQuery(
                run_id=ctx.run.id,
                ordinal=next_ordinal,
                query_kind="source_verification",
                query_text=query_text,
                source_telegram_id=candidate.telegram_id,
                state="running",
                started_at=_utcnow(),
            )
            next_ordinal += 1
            ctx.session.add(query)
            await ctx.session.flush()
            await _resume_source_verification(ctx, query, published_after)


async def _resume_source_verification(
    ctx: _WorkerContext,
    query: DiscoveryRunQuery,
    published_after: datetime,
) -> None:
    if (
        query.state == "retry_wait"
        and query.available_at
        and _ensure_utc(query.available_at) > _utcnow()
    ):
        raise _FloodWaitControl(_ensure_utc(query.available_at), query)
    telegram_id = query.source_telegram_id
    if telegram_id is None:
        await _mark_query_terminal(query, "failed", error_code="missing_source")
        return
    query.state = "running"
    await ctx.session.flush()
    request = SourceMessageSearchRequest(
        schema_version=1,
        source=SourceRef(
            schema_version=1,
            source_id=0,
            telegram_id=telegram_id,
        ),
        query=query.query_text,
        limit=MAX_MESSAGES_PER_SOURCE,
        published_after=published_after,
    )
    try:
        await _commit_before_network(ctx)
        page = await ctx.gateway.search_source_messages(request)
        query.request_count += 1
    except GatewayFloodWait as exc:
        query.state = "retry_wait"
        query.available_at = exc.until
        query.error_code = "flood_wait"
        await ctx.session.flush()
        raise _FloodWaitControl(exc.until, query) from exc
    except GatewaySourceInaccessible:
        await _mark_query_terminal(query, "failed", error_code="source_inaccessible")
        return
    except GatewayUnauthorized as exc:
        raise _SessionFatal("unauthorized") from exc
    except GatewayFrozen as exc:
        raise _SessionFatal("frozen") from exc
    except GatewayTransientError as exc:
        if await _handle_transient(ctx, query, "transient_error"):
            raise _FloodWaitControl(query.available_at or _utcnow(), query) from exc
        return
    except GatewayPermanentError:
        await _mark_query_terminal(query, "failed", error_code="permanent_error")
        await _bump_counter(ctx, "failed_queries", 1)
        return

    annotated = [
        AnnotatedSearchHit(
            hit=hit,
            query_ordinal=query.ordinal,
            discovery_channel="source_verification",
        )
        for hit in page.hits[:MAX_MESSAGES_PER_SOURCE]
    ]
    await _persist_hits(ctx, annotated)
    query.result_count = len(annotated)
    await _mark_query_terminal(query, "succeeded")


async def _phase_finalize_opportunities(ctx: _WorkerContext) -> None:
    ctx.run.phase = "I"
    await ctx.session.flush()
    evidence_rows = await _load_evidence_records(ctx)
    if not evidence_rows:
        # Keep linked-discussion opportunities already written.
        counters = _loads_counters(ctx.run.counters_json)
        counters["evidence_count"] = 0
        counters["unique_sources"] = await _opportunity_count(ctx)
        ctx.run.counters_json = _dumps_counters(counters)
        return

    # Rebuild annotated hits from persisted evidence is unnecessary — rescore
    # by grouping existing evidence rows into opportunity snapshots.
    by_source: dict[int, list[EvidenceRecord]] = {}
    for row in evidence_rows:
        by_source.setdefault(row.source_telegram_id, []).append(row)

    scored_at = _utcnow()
    qualified = 0
    for telegram_id, rows in by_source.items():
        meta = rows[0]
        source = SourceSnapshot(
            schema_version=1,
            telegram_id=telegram_id,
            username=meta.source_username or "",
            title=meta.source_title,
            source_type=meta.source_type,  # type: ignore[arg-type]
            public_url=(
                f"https://t.me/{meta.source_username}" if meta.source_username else None
            ),
            accessible=True,
        )
        identity = ctx.registry.by_telegram_id.get(telegram_id)
        snap = build_opportunity_from_evidence(
            run_id=ctx.run.id,
            source=source,
            evidence=rows,
            scored_at=scored_at,
            registry_source_id=identity.source_id if identity else None,
            linked_parent_telegram_id=ctx.linked_parents.get(telegram_id),
        )
        await _upsert_opportunity(ctx, snap)
        record_score(band=snap.band)
        qualified += sum(1 for row in rows if row.is_qualified)

    record_qualified_evidence(qualified)
    counters = _loads_counters(ctx.run.counters_json)
    counters["evidence_count"] = len(evidence_rows)
    counters["unique_sources"] = await _opportunity_count(ctx)
    ctx.run.counters_json = _dumps_counters(counters)


async def _note_registry_suppressed(
    ctx: _WorkerContext, telegram_ids: set[int] | frozenset[int]
) -> None:
    """Merge unique suppressed telegram_ids into run counter (SRC-031)."""
    if not telegram_ids:
        return
    before = len(ctx.registry_suppressed_ids)
    ctx.registry_suppressed_ids.update(telegram_ids)
    if len(ctx.registry_suppressed_ids) == before:
        return
    counters = _loads_counters(ctx.run.counters_json)
    counters["registry_suppressed"] = len(ctx.registry_suppressed_ids)
    ctx.run.counters_json = _dumps_counters(counters)


async def _note_dismissed_suppressed(
    ctx: _WorkerContext, telegram_ids: set[int] | frozenset[int]
) -> None:
    """Merge unique dismissed-suppressed telegram_ids into run counter (SRC-032)."""
    if not telegram_ids:
        return
    before = len(ctx.dismissed_suppressed_ids)
    ctx.dismissed_suppressed_ids.update(telegram_ids)
    if len(ctx.dismissed_suppressed_ids) == before:
        return
    counters = _loads_counters(ctx.run.counters_json)
    counters["dismissed_suppressed"] = len(ctx.dismissed_suppressed_ids)
    ctx.run.counters_json = _dumps_counters(counters)


async def _persist_hits(
    ctx: _WorkerContext,
    annotated: list[AnnotatedSearchHit],
) -> None:
    if not annotated:
        return
    existing = await _evidence_count(ctx)
    result = aggregate_search_hits(
        annotated,
        run_id=ctx.run.id,
        scored_at=_utcnow(),
        registry=ctx.registry,
        dismissed=ctx.dismissed,
        existing_evidence_count=existing,
        linked_parents=ctx.linked_parents,
    )
    if result.window_skipped_count:
        await _bump_counter(ctx, "window_skipped", result.window_skipped_count)
    if result.budget_skipped_count:
        await _bump_counter(ctx, "budget_skipped", result.budget_skipped_count)
    await _note_registry_suppressed(ctx, result.registry_suppressed_ids)
    await _note_dismissed_suppressed(ctx, result.dismissed_suppressed_ids)
    hits_by_kind: dict[str, int] = {}
    for item in annotated:
        hits_by_kind[item.discovery_channel] = hits_by_kind.get(item.discovery_channel, 0) + 1
    for kind, count in hits_by_kind.items():
        record_search_hits(kind=kind, count=count)
    for record in result.evidence:
        await _insert_evidence(ctx, record)
    for opportunity in result.opportunities:
        await _upsert_opportunity(ctx, opportunity)
    counters = _loads_counters(ctx.run.counters_json)
    counters["evidence_count"] = await _evidence_count(ctx)
    ctx.run.counters_json = _dumps_counters(counters)
    await ctx.session.flush()


async def _insert_evidence(ctx: _WorkerContext, record: EvidenceRecord) -> None:
    existing = await ctx.session.execute(
        select(SourceDiscoveryEvidence).where(
            SourceDiscoveryEvidence.run_id == record.run_id,
            SourceDiscoveryEvidence.source_telegram_id == record.source_telegram_id,
            SourceDiscoveryEvidence.telegram_message_id == record.telegram_message_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        # Idempotent page replay: merge ordinals/channels, keep excerpt.
        ordinals = sorted(
            set(json.loads(row.matched_query_ordinals_json))
            | set(record.matched_query_ordinals)
        )
        channels = sorted(
            set(json.loads(row.discovery_channels_json)) | set(record.discovery_channels)
        )
        row.matched_query_ordinals_json = json.dumps(ordinals, ensure_ascii=False)
        row.discovery_channels_json = json.dumps(channels, ensure_ascii=False)
        if record.is_qualified:
            row.is_qualified = True
        return

    row = SourceDiscoveryEvidence(
        run_id=record.run_id,
        source_telegram_id=record.source_telegram_id,
        source_username=record.source_username,
        source_title=record.source_title,
        source_type=record.source_type,
        telegram_message_id=record.telegram_message_id,
        published_at=record.published_at,
        permalink=record.permalink,
        excerpt=record.excerpt,
        normalized_hash=record.normalized_hash,
        matched_query_ordinals_json=record.matched_query_ordinals_json(),
        discovery_channels_json=record.discovery_channels_json(),
        detection_category=record.detection_category,
        is_qualified=record.is_qualified,
        hard_exclusion=record.hard_exclusion,
        hard_exclusion_rule_id=record.hard_exclusion_rule_id,
        service_profiles_json=record.service_profiles_json(),
        rule_set_checksum=record.rule_set_checksum,
        created_at=_utcnow(),
    )
    ctx.session.add(row)
    await ctx.session.flush()


async def _upsert_opportunity(
    ctx: _WorkerContext,
    snap: OpportunitySnapshotRecord,
) -> None:
    # SRC-031 safety net: never persist opportunity for registry-known ids.
    if snap.source_telegram_id in registry_telegram_ids(ctx.registry) or snap.source_id is not None:
        await _note_registry_suppressed(ctx, {snap.source_telegram_id})
        return
    dismissed_id = _dismissed_canonical_id(
        ctx,
        telegram_id=snap.source_telegram_id,
        username=snap.username,
    )
    if dismissed_id is not None:
        await _note_dismissed_suppressed(ctx, {dismissed_id})
        return
    existing = await ctx.session.execute(
        select(SourceOpportunitySnapshot).where(
            SourceOpportunitySnapshot.run_id == snap.run_id,
            SourceOpportunitySnapshot.source_telegram_id == snap.source_telegram_id,
        )
    )
    row = existing.scalar_one_or_none()
    now = _utcnow()
    if row is None:
        row = SourceOpportunitySnapshot(
            run_id=snap.run_id,
            source_id=snap.source_id,
            source_telegram_id=snap.source_telegram_id,
            username=snap.username,
            title=snap.title,
            source_type=snap.source_type,
            public_url=snap.public_url,
            linked_parent_telegram_id=snap.linked_parent_telegram_id,
            qualified_count=snap.qualified_count,
            excluded_count=snap.excluded_count,
            active_week_count=snap.active_week_count,
            ecommerce_qualified_count=snap.ecommerce_qualified_count,
            last_qualified_at=snap.last_qualified_at,
            sample_message_count=snap.sample_message_count,
            sample_timestamps=snap.sample_timestamps_json(),
            score=snap.score,
            band=snap.band,
            score_components_json=snap.score_components_json(),
            discovery_channels_json=snap.discovery_channels_json(),
            review_state=snap.review_state,
            version=1,
            created_at=now,
            updated_at=now,
        )
        ctx.session.add(row)
    else:
        # Do not clobber promoted/dismissed review_state mid-run.
        row.source_id = snap.source_id
        row.username = snap.username
        row.title = snap.title
        row.source_type = snap.source_type
        row.public_url = snap.public_url
        if snap.linked_parent_telegram_id is not None:
            row.linked_parent_telegram_id = snap.linked_parent_telegram_id
        row.qualified_count = snap.qualified_count
        row.excluded_count = snap.excluded_count
        row.active_week_count = snap.active_week_count
        row.ecommerce_qualified_count = snap.ecommerce_qualified_count
        row.last_qualified_at = snap.last_qualified_at
        row.sample_message_count = snap.sample_message_count
        row.sample_timestamps = snap.sample_timestamps_json()
        row.score = snap.score
        row.band = snap.band
        row.score_components_json = snap.score_components_json()
        row.discovery_channels_json = snap.discovery_channels_json()
        row.updated_at = now
        row.version += 1
    await ctx.session.flush()


async def _load_evidence_records(ctx: _WorkerContext) -> list[EvidenceRecord]:
    rows = list(
        (
            await ctx.session.execute(
                select(SourceDiscoveryEvidence).where(
                    SourceDiscoveryEvidence.run_id == ctx.run.id
                )
            )
        )
        .scalars()
        .all()
    )
    records: list[EvidenceRecord] = []
    for row in rows:
        records.append(
            EvidenceRecord(
                run_id=row.run_id,
                source_telegram_id=row.source_telegram_id,
                source_username=row.source_username,
                source_title=row.source_title,
                source_type=row.source_type,
                telegram_message_id=row.telegram_message_id,
                published_at=row.published_at,
                permalink=row.permalink,
                excerpt=row.excerpt,
                normalized_hash=row.normalized_hash,
                matched_query_ordinals=tuple(json.loads(row.matched_query_ordinals_json)),
                discovery_channels=tuple(json.loads(row.discovery_channels_json)),
                detection_category=row.detection_category,
                is_qualified=row.is_qualified,
                hard_exclusion=row.hard_exclusion,
                hard_exclusion_rule_id=row.hard_exclusion_rule_id,
                service_profiles=tuple(json.loads(row.service_profiles_json)),
                rule_set_checksum=row.rule_set_checksum,
            )
        )
    return records


async def _evidence_count(ctx: _WorkerContext) -> int:
    result = await ctx.session.execute(
        select(func.count())
        .select_from(SourceDiscoveryEvidence)
        .where(SourceDiscoveryEvidence.run_id == ctx.run.id)
    )
    return int(result.scalar_one())


async def _opportunity_count(ctx: _WorkerContext) -> int:
    result = await ctx.session.execute(
        select(func.count())
        .select_from(SourceOpportunitySnapshot)
        .where(SourceOpportunitySnapshot.run_id == ctx.run.id)
    )
    return int(result.scalar_one())


async def _channel_telegram_ids(ctx: _WorkerContext) -> list[int]:
    evidence = await _load_evidence_records(ctx)
    known = registry_telegram_ids(ctx.registry)
    ids: set[int] = set()
    for row in evidence:
        if (
            row.source_type == "channel"
            and row.source_telegram_id not in known
            and _dismissed_canonical_id(
                ctx,
                telegram_id=row.source_telegram_id,
                username=row.source_username,
            )
            is None
        ):
            ids.add(row.source_telegram_id)
    for snap in ctx.directory_sources:
        if (
            snap.source_type == "channel"
            and snap.telegram_id not in known
            and _dismissed_canonical_id(
                ctx,
                telegram_id=snap.telegram_id,
                username=snap.username,
            )
            is None
        ):
            ids.add(snap.telegram_id)
    return sorted(ids)


async def _next_ordinal(ctx: _WorkerContext) -> int:
    result = await ctx.session.execute(
        select(func.max(DiscoveryRunQuery.ordinal)).where(
            DiscoveryRunQuery.run_id == ctx.run.id
        )
    )
    current = result.scalar_one()
    return int(current or 0) + 1


async def _mark_query_terminal(
    query: DiscoveryRunQuery,
    state: str,
    *,
    error_code: str | None = None,
) -> None:
    query.state = state
    if error_code is not None:
        query.error_code = error_code
    query.finished_at = _utcnow()
    if state != "retry_wait":
        query.available_at = None
    _emit_query_observability(query, state=state, error_code=query.error_code)


def _emit_query_observability(
    query: DiscoveryRunQuery,
    *,
    state: str,
    error_code: str | None,
) -> None:
    kind = query.query_kind or "unknown"
    record_query_total(kind=kind, outcome=state)
    if state == "quota_skipped":
        # OBS-018: quota exhaustion alone must not mark discovery unhealthy.
        note_quota_skipped()
    duration_ms: int | None = None
    if query.started_at is not None and query.finished_at is not None:
        started = _ensure_utc(query.started_at)
        finished = _ensure_utc(query.finished_at)
        duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    quota_outcome = None
    if state == "quota_skipped":
        quota_outcome = error_code or "quota_exhausted"
    log_query_progress(
        run_id=query.run_id,
        query_ordinal=query.ordinal,
        method=kind,
        result_count=int(query.result_count or 0),
        error_code=error_code,
        duration_ms=duration_ms,
        quota_outcome=quota_outcome,
        outcome=state,
    )


async def _handle_transient(
    ctx: _WorkerContext,
    query: DiscoveryRunQuery,
    error_code: str,
) -> bool:
    """Return True when the job should park in retry_wait; False if query failed."""
    payload = _cursor_payload(query.cursor_json)
    attempts = int(payload.get("transient_attempts", 0)) + 1
    payload["transient_attempts"] = attempts
    _save_cursor(query, payload)
    query.error_code = error_code
    if attempts >= MAX_TRANSIENT_ATTEMPTS:
        await _mark_query_terminal(query, "failed", error_code=error_code)
        await _bump_counter(ctx, "failed_queries", 1)
        return False
    note_transient_error()
    delay = _transient_delay_seconds(attempts)
    until = _utcnow() + timedelta(seconds=delay)
    query.state = "retry_wait"
    query.available_at = until
    return True


async def _restore_linked_parents(ctx: _WorkerContext) -> None:
    snaps = (
        await ctx.session.execute(
            select(SourceOpportunitySnapshot).where(
                SourceOpportunitySnapshot.run_id == ctx.run.id,
                SourceOpportunitySnapshot.linked_parent_telegram_id.is_not(None),
            )
        )
    ).scalars()
    for snap in snaps:
        parent = snap.linked_parent_telegram_id
        if parent is not None:
            ctx.linked_parents[snap.source_telegram_id] = parent


async def _source_ids_with_query_kind(ctx: _WorkerContext, query_kind: str) -> set[int]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == query_kind,
        )
    )
    out: set[int] = set()
    for row in result.scalars():
        if row.source_telegram_id is not None:
            out.add(row.source_telegram_id)
    return out


async def _parked_queries(
    ctx: _WorkerContext,
    query_kind: str,
) -> list[DiscoveryRunQuery]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery)
        .where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == query_kind,
            DiscoveryRunQuery.state == "retry_wait",
        )
        .order_by(DiscoveryRunQuery.ordinal.asc())
    )
    return list(result.scalars().all())


async def _finished_verification_keys(ctx: _WorkerContext) -> set[tuple[int, str]]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.query_kind == "source_verification",
            DiscoveryRunQuery.state.in_(
                (
                    "succeeded",
                    "failed",
                    "cancelled",
                    "quota_skipped",
                    "budget_skipped",
                    "retry_wait",
                    "running",
                )
            ),
        )
    )
    keys: set[tuple[int, str]] = set()
    for row in result.scalars():
        if row.source_telegram_id is None:
            continue
        keys.add((row.source_telegram_id, row.query_text))
    return keys


async def _bump_counter(ctx: _WorkerContext, key: str, delta: int) -> None:
    counters = _loads_counters(ctx.run.counters_json)
    counters[key] = int(counters.get(key, 0)) + delta
    ctx.run.counters_json = _dumps_counters(counters)


async def _park_flood_wait(ctx: _WorkerContext, exc: _FloodWaitControl) -> dict[str, Any]:
    until = _ensure_utc(exc.until)
    query = exc.query
    query.state = "retry_wait"
    query.available_at = until
    is_flood = query.error_code in (None, "flood_wait") or "flood" in (
        query.error_code or ""
    )
    if is_flood and query.error_code != "transient_error":
        query.error_code = "flood_wait"
        ctx.run.state = "retry_wait_flood"
        ctx.run.last_error_code = "flood_wait"
        note_flood_wait(until=until)
    else:
        # Transient retry: keep run running (no long sleep).
        ctx.run.state = "running"
        ctx.run.last_error_code = query.error_code
    ctx.job.state = "retry_wait"
    ctx.job.available_at = until
    ctx.job.last_error_code = query.error_code
    ctx.job.lease_until = None
    ctx.job.updated_at = _utcnow()
    await ctx.session.flush()
    log_query_progress(
        run_id=ctx.run.id,
        query_ordinal=query.ordinal,
        method=query.query_kind or "unknown",
        result_count=int(query.result_count or 0),
        error_code=query.error_code,
        duration_ms=None,
        outcome="retry_wait",
    )
    return {
        "outcome": "retry_wait",
        "until": until.isoformat(),
        "query_id": query.id,
        "error_code": query.error_code,
    }


async def _mark_cancelled(ctx: _WorkerContext) -> dict[str, Any]:
    now = _utcnow()
    ctx.run.state = "cancelled"
    ctx.run.finished_at = now
    ctx.run.phase = ctx.run.phase or "cancelled"
    ctx.job.state = "cancelled"
    ctx.job.lease_until = None
    ctx.job.updated_at = now
    # Cancel remaining queued queries.
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(
            DiscoveryRunQuery.run_id == ctx.run.id,
            DiscoveryRunQuery.state.in_(("queued", "running", "retry_wait")),
        )
    )
    for query in result.scalars():
        query.state = "cancelled"
        query.finished_at = now
    await ctx.session.flush()
    _emit_run_observability(
        ctx.run,
        state="cancelled",
        evidence_count=None,
        unique_sources=None,
    )
    note_run_recovered()
    return {"outcome": "cancelled", "run_id": ctx.run.id}


async def _finish_run(ctx: _WorkerContext) -> dict[str, Any]:
    result = await ctx.session.execute(
        select(DiscoveryRunQuery).where(DiscoveryRunQuery.run_id == ctx.run.id)
    )
    queries = list(result.scalars().all())
    has_partial = any(
        q.state in ("quota_skipped", "budget_skipped", "failed") for q in queries
    )
    now = _utcnow()
    ctx.run.state = "partial" if has_partial else "succeeded"
    ctx.run.finished_at = now
    ctx.run.phase = "I"
    ctx.run.last_error_code = None
    ctx.job.state = "succeeded"
    ctx.job.lease_until = None
    ctx.job.last_error_code = None
    ctx.job.updated_at = now
    counters = _loads_counters(ctx.run.counters_json)
    counters["evidence_count"] = await _evidence_count(ctx)
    counters["unique_sources"] = await _opportunity_count(ctx)
    ctx.run.counters_json = _dumps_counters(counters)
    await ctx.session.flush()
    _emit_run_observability(
        ctx.run,
        state=ctx.run.state,
        evidence_count=counters["evidence_count"],
        unique_sources=counters["unique_sources"],
    )
    note_run_recovered()
    return {
        "outcome": ctx.run.state,
        "run_id": ctx.run.id,
        "evidence_count": counters["evidence_count"],
        "unique_sources": counters["unique_sources"],
    }


async def _fail_run(
    session: AsyncSession,
    job: Job,
    run: DiscoveryRun,
    code: str,
) -> dict[str, Any]:
    now = _utcnow()
    run.state = "failed"
    run.finished_at = now
    run.last_error_code = code
    job.state = "failed"
    job.last_error_code = code
    job.lease_until = None
    job.updated_at = now
    await session.flush()
    _emit_run_observability(
        run,
        state="failed",
        evidence_count=None,
        unique_sources=None,
        error_code=code,
    )
    return {"outcome": "failed", "error": code, "run_id": run.id}


def _emit_run_observability(
    run: DiscoveryRun,
    *,
    state: str,
    evidence_count: int | None,
    unique_sources: int | None,
    error_code: str | None = None,
) -> None:
    record_run_total(state)
    duration_ms: int | None = None
    if run.started_at is not None and run.finished_at is not None:
        started = _ensure_utc(run.started_at)
        finished = _ensure_utc(run.finished_at)
        seconds = max(0.0, (finished - started).total_seconds())
        record_run_duration_seconds(seconds)
        duration_ms = int(seconds * 1000)
    if unique_sources is not None:
        record_unique_sources(unique_sources)
    if evidence_count is not None:
        # Qualified count is emitted during finalize; keep total evidence in logs only.
        pass
    log_run_finished(
        run_id=run.id,
        state=state,
        duration_ms=duration_ms,
        error_code=error_code or run.last_error_code,
        evidence_count=evidence_count,
        unique_sources=unique_sources,
    )


__all__ = [
    "CLAIM_LOOP_IDLE_SECONDS",
    "CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS",
    "DEEP_QUERIES_PER_SOURCE",
    "DIRECTORY_PEER_LIMIT",
    "GLOBAL_MAX_PAGES",
    "GLOBAL_PAGE_SIZE",
    "HEARTBEAT_SECONDS",
    "LEASE_SECONDS",
    "MAX_TRANSIENT_ATTEMPTS",
    "TRANSIENT_RETRY_DELAYS_S",
    "KeywordDiscoveryClaimLoop",
    "claim_and_process_keyword_job",
    "process_keyword_discovery_job",
]
