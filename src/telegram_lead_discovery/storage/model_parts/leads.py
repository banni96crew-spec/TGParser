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


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("canonical_message_id", name="uq_lead_canonical_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_message_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_messages.id"), nullable=False
    )
    current_score_id: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    band: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadScore(Base):
    __tablename__ = "lead_scores"
    __table_args__ = (UniqueConstraint("lead_id", "score_version", name="uq_lead_score_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    processing_result_id: Mapped[int] = mapped_column(
        ForeignKey("processing_results.id"), nullable=False
    )
    score_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    raw_total: Mapped[int] = mapped_column(Integer, nullable=False)
    soft_penalty_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String(16), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadScoreComponent(Base):
    __tablename__ = "lead_score_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_score_id: Mapped[int] = mapped_column(ForeignKey("lead_scores.id"), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(64))
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_ru: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadFeedback(Base):
    __tablename__ = "lead_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_category: Mapped[str | None] = mapped_column(String(64))
    expected_band: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeletionTombstone(Base):
    __tablename__ = "deletion_tombstones"
    __table_args__ = (
        UniqueConstraint("entity_type", "external_identity_hash", name="uq_tombstone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupManifest(Base):
    __tablename__ = "backup_manifests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    backup_type: Mapped[str] = mapped_column(String(16), nullable=False)
    database_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    database_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    integrity_result: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
