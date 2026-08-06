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


class TelegramSource(Base):
    __tablename__ = "telegram_sources"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_sources_telegram_id"),
        UniqueConstraint("username_normalized", name="uq_sources_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer)
    username_normalized: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="channel")
    public_url: Mapped[str | None] = mapped_column(String(512))
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    access_error_code: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monitoring_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceAlias(Base):
    __tablename__ = "source_aliases"
    __table_args__ = (UniqueConstraint("normalized_username", name="uq_alias_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceApprovalEvent(Base):
    __tablename__ = "source_approval_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_source_approval_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeywordDiscoveryProfile(Base):
    __tablename__ = "keyword_discovery_profiles"
    __table_args__ = (UniqueConstraint("name", name="uq_keyword_discovery_profile_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeywordDiscoveryProfileVersion(Base):
    __tablename__ = "keyword_discovery_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_keyword_profile_id_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("keyword_discovery_profiles.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    post_queries_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    directory_queries_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    replacement_directory_queries_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    required_service_profiles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    additional_exclusions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
