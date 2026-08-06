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


class RuleSetVersion(Base):
    __tablename__ = "rule_set_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_ruleset_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, default="ru-mvp-1")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="ru")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    parent_version_id: Mapped[int | None] = mapped_column(Integer)
    hot_min: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    warm_min: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    cold_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServiceProfile(Base):
    __tablename__ = "service_profiles"
    __table_args__ = (
        UniqueConstraint("rule_set_version_id", "code", name="uq_service_profile_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name_ru: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeywordGroup(Base):
    __tablename__ = "keyword_groups"
    __table_args__ = (
        UniqueConstraint("rule_set_version_id", "code", name="uq_keyword_group_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("service_profiles.id"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    group_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_version_id", "stable_rule_id", name="uq_rule_in_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    stable_rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("keyword_groups.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    flags: Mapped[str] = mapped_column(
        String(128), nullable=False, default="IGNORECASE|FULLCASE|VERSION1"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    explanation_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    explanation_template_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DetectionResult(Base):
    __tablename__ = "detection_results"
    __table_args__ = (
        UniqueConstraint("revision_id", "rule_set_version_id", name="uq_detection_revision_rules"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_message_revisions.id"), nullable=False
    )
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    hard_exclusion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    service_profiles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    explanation_items_ru_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    counters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessingResult(Base):
    __tablename__ = "processing_results"
    __table_args__ = (
        UniqueConstraint("revision_id", "rule_set_version_id", name="uq_result_revision_rules"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    revision_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_message_revisions.id"), nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("processing_runs.id"))
    rule_set_version_id: Mapped[int] = mapped_column(
        ForeignKey("rule_set_versions.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    score_total: Mapped[int | None] = mapped_column(Integer)
    score_band: Mapped[str | None] = mapped_column(String(16))
    hard_exclusion_rule_id: Mapped[str | None] = mapped_column(String(64))
    explanation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("processing_runs.id"))
    message_id: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
