"""Promote / dismiss opportunity snapshots (SRC-026/027, D-049).

Promotion creates or links a ``TelegramSource(candidate)`` only. It MUST NOT
call ``validate_source``, approval, checkpoint creation, backfill, or monitoring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.observability.discovery import record_promotion
from telegram_lead_discovery.source_discovery.canonical_identity import (
    CanonicalSourceIdentity,
    peer_key,
)
from telegram_lead_discovery.storage.dismissed_suppress import (
    ReconsiderSuppressResult,
    SuppressIdentity,
)
from telegram_lead_discovery.storage.dismissed_suppress import (
    reconsider_dismiss_suppress as _sto_reconsider_dismiss_suppress,
)
from telegram_lead_discovery.storage.dismissed_suppress import (
    upsert_dismiss_suppress as _sto_upsert_dismiss_suppress,
)
from telegram_lead_discovery.storage.models import (
    DismissedKeywordSource,
    SourceAlias,
    SourceDiscoveryEvent,
    SourceOpportunitySnapshot,
    TelegramSource,
)

DEFAULT_CANDIDATE_QUALITY_SCORE = 2


class OpportunityNotFoundError(LookupError):
    """Raised when opportunity snapshot id is missing."""


class OpportunityVersionConflict(Exception):
    """Raised on optimistic snapshot version mismatch."""


class OpportunityReviewStateError(ValueError):
    """Raised when review_state forbids the requested transition."""


@dataclass(frozen=True, slots=True)
class PromoteOpportunityResult:
    snapshot: SourceOpportunitySnapshot
    source: TelegramSource
    method: str
    created_new: bool
    idempotent: bool


def _discovery_method(snapshot: SourceOpportunitySnapshot) -> str:
    if snapshot.linked_parent_telegram_id is not None:
        return "linked_discussion"
    return "keyword_search"


def _normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    text = username.strip().lstrip("@").lower()
    return text or None


async def _upsert_dismissed_suppress_rule(
    session: AsyncSession,
    *,
    snapshot: SourceOpportunitySnapshot,
    reason: str,
) -> DismissedKeywordSource:
    """Persist durable suppress via storage helper (canonical_key = peer:<id>)."""
    normalized = _normalize_username(snapshot.username)
    tid = int(snapshot.source_telegram_id)
    return await _sto_upsert_dismiss_suppress(
        session,
        identity=SuppressIdentity(
            canonical_key=peer_key(tid),
            telegram_id=tid,
            username_normalized=normalized,
        ),
        reason=reason,
        operator_trigger="DismissOpportunity",
        origin_run_id=snapshot.run_id,
        origin_opportunity_id=snapshot.id,
    )


async def upsert_dismiss_suppress_for_identity(
    session: AsyncSession,
    *,
    identity: CanonicalSourceIdentity,
    reason: str,
    operator_trigger: str | None = None,
    origin_run_id: int | None = None,
    origin_opportunity_id: int | None = None,
) -> DismissedKeywordSource:
    """SRC wrapper: upsert suppress membership for an explicit identity claim."""
    return await _sto_upsert_dismiss_suppress(
        session,
        identity=SuppressIdentity(
            canonical_key=identity.canonical_key,
            telegram_id=identity.telegram_id,
            username_normalized=identity.username_normalized,
        ),
        reason=reason,
        operator_trigger=operator_trigger,
        origin_run_id=origin_run_id,
        origin_opportunity_id=origin_opportunity_id,
        extra_aliases=identity.aliases,
    )


async def reconsider_dismiss_suppress(
    session: AsyncSession,
    *,
    suppress_id: int | None = None,
    canonical_key: str | None = None,
    note: str = "",
    version: int | None = None,
) -> ReconsiderSuppressResult:
    """Explicit ReconsiderDismissSuppress — removes membership + audit (SRC-036)."""
    return await _sto_reconsider_dismiss_suppress(
        session,
        suppress_id=suppress_id,
        canonical_key=canonical_key,
        note=note,
        version=version,
    )


async def _find_source_by_identity(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
) -> TelegramSource | None:
    """Identity order: telegram_id → username → SourceAlias (SRC-022)."""
    by_tid = await session.execute(
        select(TelegramSource).where(TelegramSource.telegram_id == telegram_id)
    )
    source = by_tid.scalar_one_or_none()
    if source is not None:
        return source

    normalized = _normalize_username(username)
    if normalized is None:
        return None

    by_username = await session.execute(
        select(TelegramSource).where(TelegramSource.username_normalized == normalized)
    )
    source = by_username.scalar_one_or_none()
    if source is not None:
        return source

    now = datetime.now(UTC)
    by_alias = await session.execute(
        select(SourceAlias).where(
            SourceAlias.normalized_username == normalized,
            or_(SourceAlias.valid_until.is_(None), SourceAlias.valid_until > now),
        )
    )
    alias = by_alias.scalar_one_or_none()
    if alias is None:
        return None
    return await session.get(TelegramSource, alias.source_id)


async def _resolve_parent_source_id(
    session: AsyncSession,
    linked_parent_telegram_id: int | None,
) -> int | None:
    if linked_parent_telegram_id is None:
        return None
    result = await session.execute(
        select(TelegramSource).where(TelegramSource.telegram_id == linked_parent_telegram_id)
    )
    parent = result.scalar_one_or_none()
    return None if parent is None else parent.id


async def promote_opportunity_to_candidate(
    session: AsyncSession,
    *,
    opportunity_id: int,
    version: int,
) -> PromoteOpportunityResult:
    """PromoteOpportunityToCandidate — single-transaction candidate link (SRC-026)."""
    snapshot = await session.get(SourceOpportunitySnapshot, opportunity_id)
    if snapshot is None:
        raise OpportunityNotFoundError(f"opportunity_not_found:{opportunity_id}")

    if snapshot.version != version:
        raise OpportunityVersionConflict(
            f"opportunity_version_conflict:expected={version},current={snapshot.version}"
        )

    if snapshot.review_state == "promoted":
        if snapshot.promoted_source_id is None:
            raise OpportunityReviewStateError("promoted_without_source")
        source = await session.get(TelegramSource, snapshot.promoted_source_id)
        if source is None:
            raise OpportunityReviewStateError(
                f"promoted_source_missing:{snapshot.promoted_source_id}"
            )
        record_promotion(result="idempotent")
        return PromoteOpportunityResult(
            snapshot=snapshot,
            source=source,
            method=_discovery_method(snapshot),
            created_new=False,
            idempotent=True,
        )

    if snapshot.review_state == "dismissed":
        raise OpportunityReviewStateError("opportunity_dismissed")

    if snapshot.review_state != "unreviewed":
        raise OpportunityReviewStateError(f"invalid_review_state:{snapshot.review_state}")

    method = _discovery_method(snapshot)
    existing = await _find_source_by_identity(
        session,
        telegram_id=snapshot.source_telegram_id,
        username=snapshot.username,
    )
    created_new = False
    if existing is None:
        source = TelegramSource(
            telegram_id=snapshot.source_telegram_id,
            username_normalized=_normalize_username(snapshot.username),
            title=snapshot.title,
            source_type=snapshot.source_type,
            public_url=snapshot.public_url,
            lifecycle_state="candidate",
            # Opportunity score stays on the snapshot only (SRC-025 / D-054).
            quality_score=DEFAULT_CANDIDATE_QUALITY_SCORE,
        )
        session.add(source)
        await session.flush()
        created_new = True
        outcome = "created"
    else:
        source = existing
        outcome = "merged"

    now = datetime.now(UTC)
    raw_reference = snapshot.public_url or snapshot.username or str(snapshot.source_telegram_id)
    normalized_reference = _normalize_username(snapshot.username) or str(
        snapshot.source_telegram_id
    )
    session.add(
        SourceDiscoveryEvent(
            event_id=str(uuid.uuid4()),
            run_id=snapshot.run_id,
            source_id=source.id,
            method=method,
            parent_source_id=await _resolve_parent_source_id(
                session, snapshot.linked_parent_telegram_id
            ),
            raw_reference=raw_reference,
            normalized_reference=normalized_reference,
            outcome=outcome,
            depth=0,
            discovered_at=now,
        )
    )

    snapshot.review_state = "promoted"
    snapshot.promoted_source_id = source.id
    snapshot.source_id = source.id
    snapshot.version = version + 1
    snapshot.updated_at = now
    await session.flush()

    record_promotion(result="created" if created_new else "merged")
    return PromoteOpportunityResult(
        snapshot=snapshot,
        source=source,
        method=method,
        created_new=created_new,
        idempotent=False,
    )


async def dismiss_opportunity(
    session: AsyncSession,
    *,
    opportunity_id: int,
    version: int,
    reason: str,
) -> SourceOpportunitySnapshot:
    """DismissOpportunity — mark snapshot dismissed and persist future-run suppress."""
    snapshot = await session.get(SourceOpportunitySnapshot, opportunity_id)
    if snapshot is None:
        raise OpportunityNotFoundError(f"opportunity_not_found:{opportunity_id}")

    if snapshot.version != version:
        raise OpportunityVersionConflict(
            f"opportunity_version_conflict:expected={version},current={snapshot.version}"
        )

    if snapshot.review_state == "dismissed":
        await _upsert_dismissed_suppress_rule(session, snapshot=snapshot, reason=reason)
        return snapshot

    if snapshot.review_state == "promoted":
        raise OpportunityReviewStateError("opportunity_already_promoted")

    if snapshot.review_state != "unreviewed":
        raise OpportunityReviewStateError(f"invalid_review_state:{snapshot.review_state}")

    snapshot.review_state = "dismissed"
    snapshot.dismiss_reason = reason
    snapshot.version = version + 1
    snapshot.updated_at = datetime.now(UTC)
    await _upsert_dismissed_suppress_rule(session, snapshot=snapshot, reason=reason)
    await session.flush()
    return snapshot


__all__ = [
    "DEFAULT_CANDIDATE_QUALITY_SCORE",
    "OpportunityNotFoundError",
    "OpportunityReviewStateError",
    "OpportunityVersionConflict",
    "PromoteOpportunityResult",
    "dismiss_opportunity",
    "promote_opportunity_to_candidate",
    "reconsider_dismiss_suppress",
    "upsert_dismiss_suppress_for_identity",
]
