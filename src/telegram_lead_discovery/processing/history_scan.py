"""Isolated, read-only analysis for a manually selected Telegram history window."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayPermanentError,
    GatewayRateLimited,
    GatewaySourceInaccessible,
    GatewayTimeout,
    GatewayTransientError,
    GatewayUnauthorized,
    HistoryRequest,
    PublicSourceRef,
    SourceSnapshot,
    TelegramGateway,
    TelegramMessageDTO,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.detection.errors import RuleSetInvalidError
from telegram_lead_discovery.detection.loader import get_default_loader
from telegram_lead_discovery.detection.seed import get_active_ruleset
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.scoring.engine import score_detection
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.jobs import claim_job, enqueue_job
from telegram_lead_discovery.storage.models import (
    HistoryScanResult,
    HistoryScanSession,
    HistoryScanTarget,
    Job,
    TelegramSource,
)

HISTORY_SCAN_JOB_TYPE = "history_scan"
PAGE_SIZE = 100
MAX_PERIOD = timedelta(hours=48)
MAX_SOURCES = 50
MANUAL_SOURCE_QUALITY_SCORE = 2
SUPPORTED_MANUAL_SOURCE_TYPES = frozenset({"channel", "megagroup", "group"})
MATCHED_CATEGORIES = frozenset(
    {"direct_order", "contractor_search", "recommendation_request", "vacancy"}
)
ACTIVE_STATES = ("queued", "running", "retry_wait")
RETRY_DELAYS = (1, 5, 30, 120, 600)


class HistoryScanError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScanAnalysis:
    category: str
    score_total: int
    score_band: str
    author_role: str
    author_role_rule_ids_json: str
    explanation_json: str


@dataclass(frozen=True, slots=True)
class ManualHistoryTarget:
    line_no: int
    reference: str
    snapshot: SourceSnapshot


@dataclass(frozen=True, slots=True)
class ManualHistoryRejection:
    line_no: int
    reference: str
    code: str


async def prepare_manual_history_targets(
    gateway: TelegramGateway | None, manual_refs: str
) -> tuple[list[ManualHistoryTarget], list[ManualHistoryRejection]]:
    """Resolve public manual refs before a scan is persisted.

    Rejected input deliberately never becomes a registry source or scan target.
    """
    targets: list[ManualHistoryTarget] = []
    rejections: list[ManualHistoryRejection] = []
    seen_usernames: set[str] = set()
    seen_peers: set[int] = set()
    for line_no, raw in enumerate(manual_refs.splitlines(), start=1):
        reference = raw.strip()
        if not reference:
            continue
        try:
            username = normalize_username(reference)
        except InvalidUsernameError:
            rejections.append(
                ManualHistoryRejection(line_no, reference, "manual_source_not_supported")
            )
            continue
        if username in seen_usernames:
            rejections.append(ManualHistoryRejection(line_no, reference, "duplicate_target"))
            continue
        seen_usernames.add(username)
        if gateway is None:
            rejections.append(
                ManualHistoryRejection(
                    line_no, reference, "manual_source_resolution_unavailable"
                )
            )
            continue
        try:
            snapshot = await gateway.resolve_public_source(
                PublicSourceRef(schema_version=1, username_or_url=username)
            )
        except (GatewaySourceInaccessible, GatewayPermanentError):
            rejections.append(
                ManualHistoryRejection(line_no, reference, "manual_source_not_supported")
            )
            continue
        except GatewayFloodWait:
            rejections.append(
                ManualHistoryRejection(line_no, reference, "manual_source_retry_after")
            )
            continue
        except GatewayRateLimited:
            rejections.append(
                ManualHistoryRejection(line_no, reference, "manual_source_rate_limited")
            )
            continue
        except (GatewayUnauthorized, GatewayFrozen):
            rejections.append(
                ManualHistoryRejection(line_no, reference, "telegram_account_unavailable")
            )
            continue
        except (GatewayTransientError, GatewayTimeout):
            rejections.append(
                ManualHistoryRejection(
                    line_no, reference, "manual_source_resolution_unavailable"
                )
            )
            continue
        if snapshot.source_type not in SUPPORTED_MANUAL_SOURCE_TYPES:
            rejections.append(
                ManualHistoryRejection(line_no, reference, "manual_source_not_supported")
            )
            continue
        if snapshot.telegram_id in seen_peers:
            rejections.append(ManualHistoryRejection(line_no, reference, "duplicate_target"))
            continue
        seen_peers.add(snapshot.telegram_id)
        targets.append(ManualHistoryTarget(line_no=line_no, reference=reference, snapshot=snapshot))
    return targets, rejections


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def analyze_message(
    message: TelegramMessageDTO,
    *,
    rules,
    checksum: str,
    rule_set_version_id: int,
    source_quality_score: int,
    scored_at: datetime,
    hot_min: int,
    warm_min: int,
    cold_min: int,
) -> ScanAnalysis | None:
    """Use normal detection/scoring but never create a TelegramMessage or Lead."""
    normalized = normalize_message_text(
        message.text, author_peer_id=message.author_peer_id, edited_at=None
    )
    if not normalized.analysis_text:
        return None
    detection = detect(normalized.analysis_text, rules=rules, rule_set_checksum=checksum)
    if detection.category not in MATCHED_CATEGORIES:
        return None
    score = score_detection(
        detection,
        published_at=_utc(message.published_at),
        source_quality_score=source_quality_score,
        scored_at=scored_at,
        hot_min=hot_min,
        warm_min=warm_min,
        cold_min=cold_min,
    )
    # Do not retain Telegram text or matching fragments. The link remains the proof.
    explanation = {
        "category": detection.category,
        "matched_rule_ids": [match.stable_rule_id for match in detection.matched_rules],
        "service_profiles": list(detection.service_profiles),
        "author_role": detection.author_role,
        "author_role_rule_ids": list(detection.author_role_rule_ids),
        "rule_set_version_id": rule_set_version_id,
        "rule_set_checksum": checksum,
    }
    return ScanAnalysis(
        category=detection.category,
        score_total=score.total,
        score_band=score.band,
        author_role=detection.author_role,
        author_role_rule_ids_json=json.dumps(list(detection.author_role_rule_ids)),
        explanation_json=json.dumps(explanation, ensure_ascii=False, sort_keys=True),
    )


async def create_history_scan(
    session: AsyncSession,
    *,
    source_ids: list[int],
    period_hours: int,
    manual_targets: list[ManualHistoryTarget] | None = None,
    input_rejections: list[ManualHistoryRejection] | None = None,
    now: datetime | None = None,
) -> HistoryScanSession:
    clock = _utc(now or datetime.now(UTC))
    if not 1 <= period_hours <= int(MAX_PERIOD.total_seconds() // 3600):
        raise HistoryScanError("period_hours_must_be_1_to_48")
    ids = list(dict.fromkeys(int(source_id) for source_id in source_ids))
    manual_targets = manual_targets or []
    input_rejections = input_rejections or []
    if len(ids) + len(manual_targets) > MAX_SOURCES:
        raise HistoryScanError("source_count_must_be_1_to_50")
    active = await session.execute(
        select(HistoryScanSession.id).where(HistoryScanSession.state.in_(ACTIVE_STATES)).limit(1)
    )
    if active.scalar_one_or_none() is not None:
        raise HistoryScanError("history_scan_already_active")
    sources = list(
        (
            await session.execute(
                select(TelegramSource).where(
                    TelegramSource.id.in_(ids),
                    TelegramSource.lifecycle_state == "monitoring",
                )
            )
        ).scalars()
    )
    if len(sources) != len(ids):
        raise HistoryScanError("only_monitoring_sources_allowed")
    by_id = {source.id: source for source in sources}
    sources = [by_id[source_id] for source_id in ids]
    seen_peers = {source.telegram_id for source in sources if source.telegram_id is not None}
    accepted_manual: list[ManualHistoryTarget] = []
    for manual in manual_targets:
        if manual.snapshot.telegram_id in seen_peers:
            input_rejections.append(
                ManualHistoryRejection(manual.line_no, manual.reference, "duplicate_target")
            )
            continue
        seen_peers.add(manual.snapshot.telegram_id)
        accepted_manual.append(manual)
    if not sources and not accepted_manual:
        raise HistoryScanError("source_count_must_be_1_to_50")
    ruleset = await get_active_ruleset(session)
    if ruleset is None:
        raise HistoryScanError("missing_rule_set_version")
    scan = HistoryScanSession(
        id=str(uuid.uuid4()),
        state="queued",
        from_datetime=clock - timedelta(hours=period_hours),
        to_datetime=clock,
        rule_set_version_id=ruleset.id,
        rule_set_checksum=ruleset.checksum,
        analysis_context_json=json.dumps(
            {
                "scored_at": clock.isoformat(),
                "hot_min": ruleset.hot_min,
                "warm_min": ruleset.warm_min,
                "cold_min": ruleset.cold_min,
            },
            sort_keys=True,
        ),
        input_rejections_json=json.dumps(
            [
                {"line_no": item.line_no, "reference": item.reference, "code": item.code}
                for item in input_rejections
            ],
            ensure_ascii=False,
            sort_keys=True,
        ),
        created_at=clock,
        updated_at=clock,
    )
    session.add(scan)
    await session.flush()
    ordinal = 1
    for source in sources:
        if source.telegram_id is None and not source.username_normalized:
            raise HistoryScanError("source_peer_ref_missing")
        session.add(
            HistoryScanTarget(
                session_id=scan.id,
                source_id=source.id,
                ordinal=ordinal,
                origin="monitoring",
                telegram_peer_id=source.telegram_id,
                access_hash=source.access_hash,
                username_normalized=source.username_normalized,
                source_title=source.title,
                source_quality_score=source.quality_score,
                state="queued",
                created_at=clock,
                updated_at=clock,
            )
        )
        ordinal += 1
    for manual in accepted_manual:
        snapshot = manual.snapshot
        session.add(
            HistoryScanTarget(
                session_id=scan.id,
                source_id=None,
                ordinal=ordinal,
                origin="manual",
                manual_reference=manual.reference,
                telegram_peer_id=snapshot.telegram_id,
                access_hash=snapshot.access_hash,
                username_normalized=snapshot.username.lower(),
                source_title=snapshot.title,
                source_quality_score=MANUAL_SOURCE_QUALITY_SCORE,
                state="queued",
                created_at=clock,
                updated_at=clock,
            )
        )
        ordinal += 1
    await enqueue_job(
        session,
        job_type=HISTORY_SCAN_JOB_TYPE,
        dedupe_key=f"history_scan:{scan.id}",
        payload={"session_id": scan.id},
    )
    await session.flush()
    return scan


async def cancel_history_scan(session: AsyncSession, *, session_id: str) -> bool:
    scan = await session.get(HistoryScanSession, session_id)
    if scan is None or scan.state not in ACTIVE_STATES:
        return False
    clock = datetime.now(UTC)
    scan.cancel_requested_at = clock
    scan.updated_at = clock
    jobs = list(
        (
            await session.execute(select(Job).where(Job.job_type == HISTORY_SCAN_JOB_TYPE))
        ).scalars()
    )
    for job in jobs:
        if json.loads(job.payload_json or "{}").get("session_id") == session_id:
            job.cancel_requested_at = clock
    await session.flush()
    return True


async def claim_and_process_history_scan_job(gateway: TelegramGateway) -> str | None:
    async with session_scope() as session:
        job = await claim_job(
            session, job_types=[HISTORY_SCAN_JOB_TYPE], owner="history-scan-worker"
        )
        if job is None:
            return None
        session_id = str(json.loads(job.payload_json or "{}").get("session_id", ""))
        if not session_id:
            job.state = "failed"
            job.last_error_code = "invalid_payload"
            return "failed"
        job_id = job.id
    try:
        await _process_one_target(gateway, session_id)
    except (GatewayFloodWait, GatewayRateLimited) as exc:
        await _retry_job(job_id, available_at=exc.until, flood=True)
        return "retry_wait"
    except GatewayTransientError:
        await _retry_job(job_id, available_at=None, flood=False)
        return "retry_wait"
    except (
        GatewayPermanentError,
        GatewaySourceInaccessible,
        RuleSetInvalidError,
        HistoryScanError,
    ) as exc:
        await _fail_scan(job_id, session_id, type(exc).__name__)
        return "failed"
    except Exception as exc:  # noqa: BLE001
        await _retry_job(job_id, available_at=None, flood=False)
        return type(exc).__name__
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        scan = await session.get(HistoryScanSession, session_id)
        if job is not None and scan is not None:
            if scan.cancel_requested_at is not None:
                scan.state = "cancelled"
                scan.finished_at = datetime.now(UTC)
                job.state = "cancelled"
            else:
                pending = await session.execute(
                    select(HistoryScanTarget.id).where(
                        HistoryScanTarget.session_id == session_id,
                        HistoryScanTarget.state.in_(("queued", "running")),
                    ).limit(1)
                )
                if pending.scalar_one_or_none() is None:
                    succeeded = await session.execute(
                        select(HistoryScanTarget.id)
                        .where(
                            HistoryScanTarget.session_id == session_id,
                            HistoryScanTarget.state == "succeeded",
                        )
                        .limit(1)
                    )
                    failed = await session.execute(
                        select(HistoryScanTarget.id)
                        .where(
                            HistoryScanTarget.session_id == session_id,
                            HistoryScanTarget.state.in_(("skipped", "failed")),
                        )
                        .limit(1)
                    )
                    has_succeeded = succeeded.scalar_one_or_none() is not None
                    has_failed = failed.scalar_one_or_none() is not None
                    scan.state = (
                        "partial"
                        if has_succeeded and has_failed
                        else "succeeded"
                        if has_succeeded
                        else "failed"
                    )
                    scan.finished_at = datetime.now(UTC)
                    job.state = "failed" if scan.state == "failed" else "succeeded"
                else:
                    job.state = "queued"
                    job.available_at = datetime.now(UTC)
            job.lease_until = None
            job.updated_at = datetime.now(UTC)
        await session.flush()
    return "processed"


async def _finish_target_error(
    session_id: str, target_id: int, *, state: str, code: str
) -> None:
    """Finish one target without aborting the remaining scan targets."""
    async with session_scope() as session:
        scan = await session.get(HistoryScanSession, session_id)
        target = await session.get(HistoryScanTarget, target_id)
        if scan is None or target is None:
            return
        clock = datetime.now(UTC)
        target.state = state
        target.last_error_code = code
        target.finished_at = clock
        target.updated_at = clock
        scan.state = "running"
        scan.started_at = scan.started_at or clock
        scan.updated_at = clock
        await session.flush()


async def _process_one_target(gateway: TelegramGateway, session_id: str) -> None:
    async with session_scope() as session:
        scan = await session.get(HistoryScanSession, session_id)
        if scan is None:
            raise HistoryScanError("session_not_found")
        if scan.cancel_requested_at is not None:
            return
        target = (
            await session.execute(
                select(HistoryScanTarget)
                .where(
                    HistoryScanTarget.session_id == session_id,
                    HistoryScanTarget.state.in_(("queued", "running")),
                )
                .order_by(HistoryScanTarget.ordinal.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if target is None:
            return
        target_id = target.id
        peer = TelegramPeerRef(
            schema_version=1,
            telegram_peer_id=target.telegram_peer_id,
            access_hash=target.access_hash,
            username_normalized=target.username_normalized,
        )
        request = HistoryRequest(
            schema_version=1,
            source_id=target.source_id or 0,
            peer=peer,
            limit=PAGE_SIZE,
            purpose="history_scan",
            continuation_cursor=target.continuation_cursor,
        )
        context = json.loads(scan.analysis_context_json)
        loader = get_default_loader()
        catalog = await loader.load(
            session,
            rule_set_version_id=scan.rule_set_version_id,
            checksum=scan.rule_set_checksum,
        )
        from_datetime, to_datetime = _utc(scan.from_datetime), _utc(scan.to_datetime)
        quality = target.source_quality_score

    page: list[TelegramMessageDTO] = []
    try:
        async for message in gateway.iter_history(request):
            page.append(message)
    except GatewaySourceInaccessible:
        await _finish_target_error(
            session_id, target_id, state="skipped", code="source_inaccessible"
        )
        return
    except GatewayPermanentError:
        await _finish_target_error(
            session_id, target_id, state="failed", code="gateway_permanent_error"
        )
        return
    analyses: list[tuple[TelegramMessageDTO, ScanAnalysis]] = []
    exhausted = len(page) < PAGE_SIZE
    oldest_id: int | None = None
    for message in page:
        published = _utc(message.published_at)
        oldest_id = (
            message.telegram_message_id
            if oldest_id is None
            else min(oldest_id, message.telegram_message_id)
        )
        if published < from_datetime:
            exhausted = True
            continue
        if published > to_datetime:
            continue
        analysis = analyze_message(
            message,
            rules=catalog.rules,
            checksum=catalog.checksum,
            rule_set_version_id=catalog.rule_set_version_id,
            source_quality_score=quality,
            scored_at=_utc(datetime.fromisoformat(context["scored_at"])),
            hot_min=int(context["hot_min"]),
            warm_min=int(context["warm_min"]),
            cold_min=int(context["cold_min"]),
        )
        if analysis is not None:
            analyses.append((message, analysis))
    async with session_scope() as session:
        scan = await session.get(HistoryScanSession, session_id)
        target = await session.get(HistoryScanTarget, target_id)
        if scan is None or target is None:
            raise HistoryScanError("session_or_target_not_found")
        if scan.cancel_requested_at is not None:
            target.state = "cancelled"
            target.finished_at = datetime.now(UTC)
            return
        clock = datetime.now(UTC)
        scan.state = "running"
        scan.started_at = scan.started_at or clock
        target.state = "running"
        target.started_at = target.started_at or clock
        target.messages_scanned += len(page)
        target.continuation_cursor = str(oldest_id) if oldest_id is not None else None
        new_results = 0
        for message, analysis in analyses:
            existing = await session.execute(
                select(HistoryScanResult.id).where(
                    HistoryScanResult.target_id == target.id,
                    HistoryScanResult.telegram_message_id == message.telegram_message_id,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue
            session.add(
                HistoryScanResult(
                    session_id=session_id,
                    target_id=target.id,
                    source_id=target.source_id,
                    telegram_message_id=message.telegram_message_id,
                    published_at=_utc(message.published_at),
                    permalink=message.permalink,
                    category=analysis.category,
                    score_total=analysis.score_total,
                    score_band=analysis.score_band,
                    author_role=analysis.author_role,
                    author_role_rule_ids_json=analysis.author_role_rule_ids_json,
                    explanation_json=analysis.explanation_json,
                    created_at=clock,
                )
            )
            new_results += 1
        target.results_found += new_results
        if exhausted or oldest_id is None:
            target.state = "succeeded"
            target.finished_at = clock
            target.continuation_cursor = None
        target.updated_at = clock
        scan.updated_at = clock
        await session.flush()


async def _retry_job(job_id: int, *, available_at: datetime | None, flood: bool) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        now = datetime.now(UTC)
        if flood:
            job.attempt = max(0, job.attempt - 1)
            job.available_at = available_at
            job.last_error_code = "flood_wait"
        elif job.attempt >= len(RETRY_DELAYS):
            job.state = "dead"
            job.last_error_code = "transient_retry_exhausted"
            job.lease_until = None
            return
        else:
            job.available_at = now + timedelta(seconds=RETRY_DELAYS[job.attempt - 1])
            job.last_error_code = "transient_error"
        job.state = "retry_wait"
        job.lease_until = None
        job.updated_at = now


async def _fail_scan(job_id: int, session_id: str, error_code: str) -> None:
    async with session_scope() as session:
        now = datetime.now(UTC)
        job = await session.get(Job, job_id)
        scan = await session.get(HistoryScanSession, session_id)
        if job is not None:
            job.state = "failed"
            job.last_error_code = error_code[:64]
            job.lease_until = None
            job.updated_at = now
        if scan is not None:
            scan.state = "failed"
            scan.last_error_code = error_code[:64]
            scan.finished_at = now
            scan.updated_at = now
        await session.flush()
