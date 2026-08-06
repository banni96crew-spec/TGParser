from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import (
    _WorkerContext,
    _dumps_counters,
    _loads_counters,
    _utcnow,
)
from telegram_lead_discovery.source_discovery.worker_parts.control import _bump_counter
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _dismissed_canonical_id,
    _presented_canonical_id,
)
from telegram_lead_discovery.source_discovery.worker_parts.repository import _evidence_count


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


async def _note_presented_suppressed(
    ctx: _WorkerContext, telegram_ids: set[int] | frozenset[int]
) -> None:
    """Merge unique already-shown peers into presented/cooldown counters (SRC-041)."""
    if not telegram_ids:
        return
    before = len(ctx.presented_suppressed_ids)
    ctx.presented_suppressed_ids.update(telegram_ids)
    if len(ctx.presented_suppressed_ids) == before:
        return
    unique = len(ctx.presented_suppressed_ids)
    counters = _loads_counters(ctx.run.counters_json)
    counters["presented_suppressed"] = unique
    counters["cooldown_suppressed"] = unique
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
        presented=ctx.presented,
        existing_evidence_count=existing,
        linked_parents=ctx.linked_parents,
    )
    if result.window_skipped_count:
        await _bump_counter(ctx, "window_skipped", result.window_skipped_count)
    if result.budget_skipped_count:
        await _bump_counter(ctx, "budget_skipped", result.budget_skipped_count)
    await _note_registry_suppressed(ctx, result.registry_suppressed_ids)
    await _note_dismissed_suppressed(ctx, result.dismissed_suppressed_ids)
    await _note_presented_suppressed(ctx, result.presented_suppressed_ids)
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


async def _record_presented_ledger(
    ctx: _WorkerContext,
    *,
    snap: OpportunitySnapshotRecord,
    opportunity_row: SourceOpportunitySnapshot,
) -> None:
    """Persist durable already-shown membership (idempotent; cross-run suppress)."""
    tid = snap.source_telegram_id
    await upsert_presented_suppress(
        ctx.session,
        identity=SuppressIdentity(
            canonical_key=peer_canonical_key(tid),
            telegram_id=tid,
            username_normalized=snap.username,
        ),
        origin_run_id=ctx.run.id,
        origin_opportunity_id=opportunity_row.id,
        first_presented_at=opportunity_row.created_at,
    )


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
            set(json.loads(row.matched_query_ordinals_json)) | set(record.matched_query_ordinals)
        )
        channels = sorted(
            set(json.loads(row.discovery_channels_json)) | set(record.discovery_channels)
        )
        row.matched_query_ordinals_json = json.dumps(ordinals, ensure_ascii=False)
        row.discovery_channels_json = json.dumps(channels, ensure_ascii=False)
        if record.is_qualified:
            row.is_qualified = True
        if record.matched_rule_ids:
            existing_ids = json.loads(getattr(row, "matched_rule_ids_json", None) or "[]")
            merged_ids = sorted(set(existing_ids) | set(record.matched_rule_ids))
            row.matched_rule_ids_json = json.dumps(merged_ids, ensure_ascii=False)
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
        matched_rule_ids_json=record.matched_rule_ids_json(),
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
    presented_id = _presented_canonical_id(
        ctx,
        telegram_id=snap.source_telegram_id,
        username=snap.username,
    )
    if presented_id is not None:
        await _note_presented_suppressed(ctx, {presented_id})
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
            truth_status=snap.truth_status,
            verification_scanned_count=snap.verification_scanned_count,
            verification_stop_reason=snap.verification_stop_reason,
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
        if snap.verification_scanned_count:
            row.verification_scanned_count = snap.verification_scanned_count
        if snap.verification_stop_reason:
            row.verification_stop_reason = snap.verification_stop_reason
        if snap.truth_status and snap.truth_status != "inconclusive":
            row.truth_status = snap.truth_status
        row.score_components_json = snap.score_components_json()
        row.discovery_channels_json = snap.discovery_channels_json()
        row.updated_at = now
        row.version += 1
    await ctx.session.flush()
    await _record_presented_ledger(ctx, snap=snap, opportunity_row=row)
