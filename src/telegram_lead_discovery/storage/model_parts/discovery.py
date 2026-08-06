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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from telegram_lead_discovery.storage.model_parts.base import Base, utcnow


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="graph")
    root_source_ids_json: Mapped[str | None] = mapped_column(Text, default="[]")
    profile_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("keyword_discovery_profile_versions.id")
    )
    search_mode: Mapped[str | None] = mapped_column(String(32))
    rule_set_version_id: Mapped[int | None] = mapped_column(Integer)
    rule_set_checksum: Mapped[str | None] = mapped_column(String(64))
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    expansion_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    candidate_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    phase: Mapped[str | None] = mapped_column(String(32))
    quota_snapshot_json: Mapped[str | None] = mapped_column(Text)
    cursor_json: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    counters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reference_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gate_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="inconclusive", server_default="inconclusive"
    )
    pool_exhausted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    pool_exhausted_reason: Mapped[str | None] = mapped_column(String(64))
    run_termination_reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryRunQuery(Base):
    __tablename__ = "discovery_run_queries"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_discovery_run_query_ordinal"),
        Index("ix_discovery_run_queries_run_state", "run_id", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    query_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    query_text: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_telegram_id: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    cursor_json: Mapped[str | None] = mapped_column(Text)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceDiscoveryEvidence(Base):
    __tablename__ = "source_discovery_evidence"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_telegram_id",
            "telegram_message_id",
            name="uq_evidence_run_source_message",
        ),
        Index("ix_evidence_run_source_telegram_id", "run_id", "source_telegram_id"),
        Index("ix_source_discovery_evidence_created_at", "created_at"),
        CheckConstraint(
            "author_key IS NULL OR length(author_key) = 64",
            name="ck_source_discovery_evidence_author_key",
        ),
        CheckConstraint(
            "author_kind IN ('user','bot','channel','anonymous','unknown')",
            name="ck_source_discovery_evidence_author_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False)
    source_telegram_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_username: Mapped[str | None] = mapped_column(String(64))
    source_title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    author_key: Mapped[str | None] = mapped_column(String(64))
    author_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(512))
    excerpt: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    matched_query_ordinals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    discovery_channels_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    detection_category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_qualified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hard_exclusion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hard_exclusion_rule_id: Mapped[str | None] = mapped_column(String(64))
    service_profiles_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rule_set_checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    matched_rule_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceOpportunitySnapshot(Base):
    __tablename__ = "source_opportunity_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_telegram_id",
            name="uq_opportunity_run_source_telegram_id",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_opportunity_score_0_100"),
        Index("ix_opportunity_run_score_desc", "run_id", text("score DESC")),
        Index("ix_source_opportunity_snapshots_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_sources.id"))
    source_telegram_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_url: Mapped[str | None] = mapped_column(String(512))
    linked_parent_telegram_id: Mapped[int | None] = mapped_column(Integer)
    qualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_week_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ecommerce_qualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_timestamps: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    band: Mapped[str] = mapped_column(String(16), nullable=False, default="weak")
    truth_status: Mapped[str] = mapped_column(String(16), nullable=False, default="inconclusive")
    verification_scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_stop_reason: Mapped[str | None] = mapped_column(String(64))
    activity_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    activity_active_day_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    activity_distinct_author_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    client_request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    client_request_author_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    hard_excluded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unknown_author_message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    latest_client_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    qualification_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="legacy", server_default="legacy"
    )
    qualification_reasons_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )

    score_components_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    discovery_channels_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default="unreviewed")
    promoted_source_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_sources.id"))
    dismiss_reason: Mapped[str | None] = mapped_column(String(512))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryTerminalOutcome(Base):
    __tablename__ = "discovery_terminal_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_canonical_key",
            "terminal_outcome_version",
            name="uq_discovery_terminal_outcome_version",
        ),
        CheckConstraint(
            "truth_status IN ('quality','near','inconclusive','rejected')",
            name="ck_discovery_terminal_outcome_truth",
        ),
        CheckConstraint(
            "verification_stop_reason IN "
            "('quality_reached','window_complete','history_exhausted','source_cap',"
            "'run_cap','inaccessible','cancelled')",
            name="ck_discovery_terminal_outcome_stop_reason",
        ),
        Index("ix_discovery_terminal_outcomes_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False)
    source_canonical_key: Mapped[str] = mapped_column(String(96), nullable=False)
    terminal_outcome_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    truth_status: Mapped[str] = mapped_column(String(16), nullable=False)
    verification_stop_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    activity_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_active_day_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_distinct_author_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_request_author_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hard_excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_author_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_client_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    threshold_activity_messages: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_activity_days: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_activity_authors: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_client_requests: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_client_authors: Mapped[bool] = mapped_column(Boolean, nullable=False)
    threshold_freshness: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
