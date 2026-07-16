"""Processing pipeline stages (D-040)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.detection.engine import detect
from telegram_lead_discovery.detection.seed import get_active_ruleset, seed_ruleset_ru_mvp_1
from telegram_lead_discovery.processing.normalization import normalize_message_text
from telegram_lead_discovery.scoring.engine import score_detection
from telegram_lead_discovery.storage.models import (
    DuplicateGroup,
    Lead,
    LeadScore,
    LeadScoreComponent,
    MessageDuplicate,
    ProcessingResult,
    TelegramEventEnvelope,
    TelegramMessage,
    TelegramMessageRevision,
    TelegramSource,
)
from telegram_lead_discovery.storage.outbox import enqueue_hot_lead

DEDUPE_WINDOW_DAYS = 30
LEASE_SECONDS = 300


async def recover_stale_envelopes(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Return expired processing leases to queued (PROC-017)."""
    clock = now or datetime.now(UTC)
    result = await session.execute(
        select(TelegramEventEnvelope).where(
            TelegramEventEnvelope.processing_state == "processing",
            TelegramEventEnvelope.lease_until.is_not(None),
            TelegramEventEnvelope.lease_until < clock,
        )
    )
    count = 0
    for envelope in result.scalars():
        envelope.processing_state = "queued"
        envelope.lease_owner = None
        envelope.lease_until = None
        count += 1
    if count:
        await session.flush()
    return count


async def claim_envelope(
    session: AsyncSession,
    *,
    owner: str,
    now: datetime | None = None,
) -> TelegramEventEnvelope | None:
    clock = now or datetime.now(UTC)
    await recover_stale_envelopes(session, now=clock)
    result = await session.execute(
        select(TelegramEventEnvelope)
        .where(
            or_(
                TelegramEventEnvelope.processing_state.in_(("queued", "retry_wait")),
                and_(
                    TelegramEventEnvelope.processing_state == "processing",
                    TelegramEventEnvelope.lease_until.is_not(None),
                    TelegramEventEnvelope.lease_until < clock,
                ),
            ),
        )
        .order_by(TelegramEventEnvelope.id.asc())
        .limit(1)
    )
    envelope = result.scalar_one_or_none()
    if envelope is None:
        return None
    envelope.processing_state = "processing"
    envelope.lease_owner = owner
    envelope.lease_until = clock + timedelta(seconds=LEASE_SECONDS)
    envelope.attempt += 1
    await session.flush()
    return envelope


async def process_envelope(
    session: AsyncSession,
    envelope: TelegramEventEnvelope,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run D-040 stages for one claimed envelope."""
    clock = now or datetime.now(UTC)
    payload = json.loads(envelope.payload_json or "{}")
    text = payload.get("text") or ""
    author_peer_id = payload.get("author_peer_id")
    edited_at = payload.get("edited_at")
    published_raw = payload.get("published_at")
    if published_raw:
        published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
    else:
        published_at = envelope.received_at
    permalink = payload.get("permalink")

    if envelope.event_type == "message_deleted":
        return await _handle_delete(session, envelope, clock)

    norms = normalize_message_text(
        text, author_peer_id=author_peer_id, edited_at=edited_at
    )

    # revision / upsert message
    msg_result = await session.execute(
        select(TelegramMessage).where(
            TelegramMessage.source_id == envelope.source_id,
            TelegramMessage.telegram_message_id == envelope.telegram_message_id,
        )
    )
    message = msg_result.scalar_one_or_none()
    created_revision = False
    if message is None:
        message = TelegramMessage(
            source_id=envelope.source_id,
            telegram_message_id=envelope.telegram_message_id,
            published_at=published_at,
            edited_at=datetime.fromisoformat(edited_at.replace("Z", "+00:00"))
            if edited_at
            else None,
            original_text=text,
            normalized_text=norms.dedup_text,
            normalized_hash=norms.dedup_hash,
            permalink=permalink,
            state="active",
            is_canonical=True,
        )
        session.add(message)
        await session.flush()
        revision = TelegramMessageRevision(
            message_id=message.id,
            revision_no=1,
            event_type="new" if envelope.event_type == "message_new" else "edit",
            text=norms.display_text,
            normalized_hash=norms.dedup_hash,
            content_fingerprint=norms.content_fingerprint,
            observed_at=clock,
        )
        session.add(revision)
        await session.flush()
        created_revision = True
    else:
        # idempotent replay if same fingerprint on latest revision
        rev_result = await session.execute(
            select(TelegramMessageRevision)
            .where(TelegramMessageRevision.message_id == message.id)
            .order_by(TelegramMessageRevision.revision_no.desc())
            .limit(1)
        )
        latest = rev_result.scalar_one_or_none()
        if latest is not None and latest.content_fingerprint == norms.content_fingerprint:
            envelope.processing_state = "acked"
            envelope.lease_owner = None
            envelope.lease_until = None
            await session.flush()
            return {"outcome": "idempotent_replay", "message_id": message.id}

        next_no = 1 if latest is None else latest.revision_no + 1
        message.original_text = text
        message.normalized_text = norms.dedup_text
        message.normalized_hash = norms.dedup_hash
        message.updated_at = clock
        if edited_at:
            message.edited_at = datetime.fromisoformat(edited_at.replace("Z", "+00:00"))
        revision = TelegramMessageRevision(
            message_id=message.id,
            revision_no=next_no,
            event_type="edit" if envelope.event_type == "message_edited" else "new",
            text=norms.display_text,
            normalized_hash=norms.dedup_hash,
            content_fingerprint=norms.content_fingerprint,
            observed_at=clock,
        )
        session.add(revision)
        await session.flush()
        created_revision = True

    # exact cross-source dedupe
    canonical = await _apply_exact_dedupe(session, message, norms.dedup_hash, clock)

    ruleset = await get_active_ruleset(session)
    if ruleset is None:
        ruleset = await seed_ruleset_ru_mvp_1(session)

    if not canonical.is_canonical or not norms.analysis_text:
        result = ProcessingResult(
            message_id=message.id,
            revision_id=revision.id,
            rule_set_version_id=ruleset.id,
            category="duplicate_suppressed" if not canonical.is_canonical else "empty",
            score_total=None,
            score_band=None,
            hard_exclusion_rule_id=None,
            explanation_json=json.dumps(
                {"reason": "duplicate_suppressed" if not canonical.is_canonical else "empty_text"},
                ensure_ascii=False,
            ),
            is_lead=False,
            processed_at=clock,
        )
        session.add(result)
        envelope.processing_state = "acked"
        envelope.lease_owner = None
        envelope.lease_until = None
        await session.flush()
        return {
            "outcome": "duplicate_suppressed" if not canonical.is_canonical else "empty",
            "message_id": message.id,
            "created_revision": created_revision,
        }

    source = await session.get(TelegramSource, canonical.source_id)
    quality = source.quality_score if source is not None else 2

    detection = detect(norms.analysis_text)
    score = score_detection(
        detection,
        published_at=canonical.published_at,
        source_quality_score=quality,
        scored_at=clock,
        hot_min=ruleset.hot_min,
        warm_min=ruleset.warm_min,
        cold_min=ruleset.cold_min,
    )

    explanation = {
        "category": detection.category,
        "matched_rules": [
            {
                "stable_rule_id": m.stable_rule_id,
                "dimension": m.dimension,
                "weight": m.weight,
                "matched_excerpt": m.matched_excerpt,
            }
            for m in detection.matched_rules
        ],
        "signals": detection.signals,
        "service_profiles": list(detection.service_profiles),
    }
    proc = ProcessingResult(
        message_id=canonical.id,
        revision_id=revision.id,
        rule_set_version_id=ruleset.id,
        category=detection.category,
        score_total=score.total,
        score_band=score.band,
        hard_exclusion_rule_id=detection.hard_exclusion_rule_id,
        explanation_json=json.dumps(explanation, ensure_ascii=False),
        is_lead=score.create_lead,
        processed_at=clock,
    )
    session.add(proc)
    await session.flush()

    lead: Lead | None = None
    outbox_created = False
    lead_result = await session.execute(
        select(Lead).where(Lead.canonical_message_id == canonical.id)
    )
    lead = lead_result.scalar_one_or_none()
    previous_band = lead.band if lead is not None else None

    if score.create_lead:
        if lead is None:
            lead = Lead(
                canonical_message_id=canonical.id,
                category=detection.category,
                band=score.band,
                status="new",
                last_activity_at=clock,
            )
            session.add(lead)
            await session.flush()
            previous_band = None
        else:
            lead.category = detection.category
            lead.band = score.band
            lead.last_activity_at = clock
            lead.updated_at = clock
            await session.flush()

        score_version = 1
        if lead.current_score_id is not None:
            prev_score = await session.get(LeadScore, lead.current_score_id)
            if prev_score is not None:
                score_version = prev_score.score_version + 1

        lead_score = LeadScore(
            lead_id=lead.id,
            processing_result_id=proc.id,
            score_version=score_version,
            rule_set_version_id=ruleset.id,
            raw_total=score.raw_total,
            soft_penalty_total=score.soft_penalty_total,
            total=score.total,
            band=score.band,
            scored_at=clock,
        )
        session.add(lead_score)
        await session.flush()
        for comp in score.components:
            session.add(
                LeadScoreComponent(
                    lead_score_id=lead_score.id,
                    rule_id=comp.rule_id,
                    dimension=comp.dimension,
                    value=comp.value,
                    reason_ru=comp.reason_ru,
                )
            )
        lead.current_score_id = lead_score.id
        await session.flush()

        if score.band == "hot" and previous_band != "hot":
            row = await enqueue_hot_lead(
                session, lead_id=lead.id, score_version=score_version
            )
            outbox_created = row is not None
    elif lead is not None:
        # Rescore may set Lead.band=irrelevant while keeping history (D-042).
        lead.band = "irrelevant"
        lead.updated_at = clock
        await session.flush()

    canonical.last_processed_rule_version_id = ruleset.id
    envelope.processing_state = "acked"
    envelope.lease_owner = None
    envelope.lease_until = None
    await session.flush()
    return {
        "outcome": "processed",
        "message_id": canonical.id,
        "lead_id": lead.id if lead is not None and score.create_lead else None,
        "band": score.band,
        "total": score.total,
        "outbox_created": outbox_created,
        "category": detection.category,
    }


async def _handle_delete(
    session: AsyncSession,
    envelope: TelegramEventEnvelope,
    clock: datetime,
) -> dict[str, Any]:
    msg_result = await session.execute(
        select(TelegramMessage).where(
            TelegramMessage.source_id == envelope.source_id,
            TelegramMessage.telegram_message_id == envelope.telegram_message_id,
        )
    )
    message = msg_result.scalar_one_or_none()
    if message is not None and message.deleted_at is None:
        message.deleted_at = clock
        message.state = "deleted"
        message.is_canonical = False
        message.updated_at = clock
    envelope.processing_state = "acked"
    envelope.lease_owner = None
    envelope.lease_until = None
    await session.flush()
    return {"outcome": "deleted", "message_id": message.id if message else None}


async def _apply_exact_dedupe(
    session: AsyncSession,
    message: TelegramMessage,
    dedup_hash: str,
    clock: datetime,
) -> TelegramMessage:
    if not dedup_hash or not message.normalized_text:
        message.is_canonical = True
        message.canonical_message_id = message.id
        await session.flush()
        return message

    window_start = message.published_at - timedelta(days=DEDUPE_WINDOW_DAYS)
    window_end = message.published_at + timedelta(days=DEDUPE_WINDOW_DAYS)
    result = await session.execute(
        select(TelegramMessage).where(
            TelegramMessage.normalized_hash == dedup_hash,
            TelegramMessage.deleted_at.is_(None),
            TelegramMessage.published_at >= window_start,
            TelegramMessage.published_at <= window_end,
            TelegramMessage.id != message.id,
        )
    )
    peers = list(result.scalars().all())
    if not peers:
        message.is_canonical = True
        message.canonical_message_id = message.id
        await session.flush()
        return message

    members = [message, *peers]

    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    # canonical: earliest published_at, then lowest source_id, then lowest telegram_message_id
    members.sort(
        key=lambda m: (_aware(m.published_at), m.source_id, m.telegram_message_id, m.id)
    )
    canonical = members[0]
    earliest_date = _aware(canonical.published_at).date().isoformat()
    group_key = f"{dedup_hash}:{earliest_date}"

    group_result = await session.execute(
        select(DuplicateGroup).where(DuplicateGroup.group_key == group_key)
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        group = DuplicateGroup(
            group_key=group_key,
            canonical_message_id=canonical.id,
        )
        session.add(group)
        await session.flush()
    else:
        group.canonical_message_id = canonical.id
        group.updated_at = clock

    for member in members:
        member.is_canonical = member.id == canonical.id
        member.canonical_message_id = canonical.id
        if member.id != canonical.id:
            existing_dup = await session.get(MessageDuplicate, member.id)
            if existing_dup is None:
                session.add(
                    MessageDuplicate(
                        duplicate_message_id=member.id,
                        duplicate_group_id=group.id,
                        canonical_message_id=canonical.id,
                        method="exact_normalized_hash",
                        window_days=DEDUPE_WINDOW_DAYS,
                        linked_at=clock,
                    )
                )
            else:
                existing_dup.duplicate_group_id = group.id
                existing_dup.canonical_message_id = canonical.id
    await session.flush()
    # Return the message being processed (may be non-canonical after linking).
    return message


async def process_next_envelope(
    session: AsyncSession,
    *,
    owner: str = "processor",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    envelope = await claim_envelope(session, owner=owner, now=now)
    if envelope is None:
        return None
    return await process_envelope(session, envelope, now=now)
