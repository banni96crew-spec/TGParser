from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.core import _WorkerContext
from telegram_lead_discovery.source_discovery.worker_parts.registry import _dismissed_canonical_id


async def _load_evidence_records(ctx: _WorkerContext) -> list[EvidenceRecord]:
    rows = list(
        (
            await ctx.session.execute(
                select(SourceDiscoveryEvidence).where(SourceDiscoveryEvidence.run_id == ctx.run.id)
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
                matched_rule_ids=tuple(
                    json.loads(getattr(row, "matched_rule_ids_json", None) or "[]")
                ),
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
        select(func.max(DiscoveryRunQuery.ordinal)).where(DiscoveryRunQuery.run_id == ctx.run.id)
    )
    current = result.scalar_one()
    return int(current or 0) + 1
