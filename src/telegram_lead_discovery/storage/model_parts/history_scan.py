"""Read-only manual Telegram history scan persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from telegram_lead_discovery.storage.model_parts.base import Base, utcnow


class HistoryScanSession(Base):
    __tablename__ = "history_scan_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    from_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    rule_set_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HistoryScanTarget(Base):
    __tablename__ = "history_scan_targets"
    __table_args__ = (
        UniqueConstraint("session_id", "source_id", name="uq_history_scan_target_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("history_scan_sessions.id"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    telegram_peer_id: Mapped[int | None] = mapped_column(Integer)
    access_hash: Mapped[int | None] = mapped_column(Integer)
    username_normalized: Mapped[str | None] = mapped_column(String(64))
    source_title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    continuation_cursor: Mapped[str | None] = mapped_column(String(64))
    messages_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    results_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HistoryScanResult(Base):
    __tablename__ = "history_scan_results"
    __table_args__ = (
        UniqueConstraint(
            "target_id", "telegram_message_id", name="uq_history_scan_result_message"
        ),
        Index("ix_history_scan_results_session_published", "session_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("history_scan_sessions.id"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("history_scan_targets.id"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    score_total: Mapped[int] = mapped_column(Integer, nullable=False)
    score_band: Mapped[str] = mapped_column(String(32), nullable=False)
    explanation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
