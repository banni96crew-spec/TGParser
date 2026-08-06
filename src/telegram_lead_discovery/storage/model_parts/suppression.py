from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from telegram_lead_discovery.storage.model_parts.base import Base, utcnow


class DismissedKeywordSource(Base):
    """Durable dismiss suppress ledger (STO-017 / SRC-035; physical owner STO)."""

    __tablename__ = "dismissed_keyword_sources"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_dismissed_keyword_sources_canonical_key"),
        UniqueConstraint("source_telegram_id", name="uq_dismissed_keyword_source_telegram_id"),
        Index("ix_dismissed_keyword_sources_username", "username_normalized"),
        Index("ix_dismissed_keyword_sources_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_key: Mapped[str] = mapped_column(String(96), nullable=False)
    # Nullable for provisional username:<casefold> rows until peer resolve (SRC-034).
    source_telegram_id: Mapped[int | None] = mapped_column(Integer)
    username_normalized: Mapped[str | None] = mapped_column(String(64))
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    dismiss_reason: Mapped[str | None] = mapped_column(String(512))
    origin_run_id: Mapped[int | None] = mapped_column(Integer)
    origin_opportunity_id: Mapped[int | None] = mapped_column(Integer)
    operator_trigger: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(DismissedKeywordSource, "before_insert")
@event.listens_for(DismissedKeywordSource, "before_update")
def _dismissed_keyword_source_ensure_canonical_key(mapper, connection, target) -> None:
    """Derive canonical_key for Wave-01 writers that only set source_telegram_id."""
    del mapper, connection
    if getattr(target, "canonical_key", None):
        return
    tid = getattr(target, "source_telegram_id", None)
    if tid is not None:
        target.canonical_key = f"peer:{int(tid)}"
        return
    username = getattr(target, "username_normalized", None)
    if username:
        target.canonical_key = f"username:{str(username).casefold()}"


class PresentedKeywordSource(Base):
    """Durable already-shown suppress ledger (STO-020 / SRC-041/050 / D-069)."""

    __tablename__ = "presented_keyword_sources"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_presented_keyword_sources_canonical_key"),
        UniqueConstraint("source_telegram_id", name="uq_presented_keyword_source_telegram_id"),
        Index("ix_presented_keyword_sources_username", "username_normalized"),
        Index("ix_presented_keyword_sources_first_presented_at", "first_presented_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_telegram_id: Mapped[int | None] = mapped_column(Integer)
    username_normalized: Mapped[str | None] = mapped_column(String(64))
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    origin_run_id: Mapped[int | None] = mapped_column(Integer)
    origin_opportunity_id: Mapped[int | None] = mapped_column(Integer)
    first_presented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(PresentedKeywordSource, "before_insert")
@event.listens_for(PresentedKeywordSource, "before_update")
def _presented_keyword_source_ensure_canonical_key(mapper, connection, target) -> None:
    del mapper, connection
    if getattr(target, "canonical_key", None):
        return
    tid = getattr(target, "source_telegram_id", None)
    if tid is not None:
        target.canonical_key = f"peer:{int(tid)}"
        return
    username = getattr(target, "username_normalized", None)
    if username:
        target.canonical_key = f"username:{str(username).casefold()}"


class DismissSuppressReconsideredEvent(Base):
    """Authoritative audit for ReconsiderDismissSuppress (SRC-035/036; STO physical)."""

    __tablename__ = "dismiss_suppress_reconsidered_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_dismiss_suppress_reconsidered_event_id"),
        Index("ix_dismiss_suppress_reconsidered_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_key: Mapped[str | None] = mapped_column(String(96))
    suppress_id: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceDiscoveryEvent(Base):
    __tablename__ = "source_discovery_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_discovery_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_sources.id"))
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_source_id: Mapped[int | None] = mapped_column(Integer)
    evidence_message_id: Mapped[int | None] = mapped_column(Integer)
    evidence_url: Mapped[str | None] = mapped_column(String(512))
    raw_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
