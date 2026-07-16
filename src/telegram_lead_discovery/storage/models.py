from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class OperatorSetting(Base):
    __tablename__ = "operator_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettingChange(Base):
    __tablename__ = "setting_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value_json: Mapped[str | None] = mapped_column(Text)
    new_value_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(256))
    change_source: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
        CheckConstraint(
            "(lead_id IS NOT NULL AND incident_id IS NULL) OR "
            "(lead_id IS NULL AND incident_id IS NOT NULL)",
            name="ck_outbox_lead_xor_incident",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    lead_id: Mapped[int | None] = mapped_column(Integer)
    incident_id: Mapped[str | None] = mapped_column(String(128))
    score_version: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automatic_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("outbox_id", "attempt_no", name="uq_delivery_attempt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbox_id: Mapped[int] = mapped_column(ForeignKey("notification_outbox.id"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_chat_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="env")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_code: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComponentHealth(Base):
    __tablename__ = "component_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="starting")
    reason_code: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricBucket(Base):
    __tablename__ = "metric_buckets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    labels_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sum: Mapped[float] = mapped_column(nullable=False, default=0.0)
    min: Mapped[float | None] = mapped_column()
    max: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    expansion_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    candidate_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    counters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_ref: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    health_state: Mapped[str] = mapped_column(String(32), nullable=False, default="disconnected")
    session_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    expected_account_id: Mapped[int | None] = mapped_column(Integer)
    flood_wait_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectorCheckpoint(Base):
    __tablename__ = "collector_checkpoints"

    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), primary_key=True)
    last_committed_message_id: Mapped[int | None] = mapped_column(Integer)
    last_committed_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramEventEnvelope(Base):
    __tablename__ = "telegram_event_envelopes"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "telegram_message_id",
            "event_type",
            "edit_key",
            name="uq_envelope_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edit_key: Mapped[str] = mapped_column(String(64), nullable=False, default="0")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    collection_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processing_state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramAuthor(Base):
    __tablename__ = "telegram_authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(256))
    explicit_contact_text: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (
        UniqueConstraint("source_id", "telegram_message_id", name="uq_message_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("telegram_sources.id"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_authors.id"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    permalink: Mapped[str | None] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    canonical_message_id: Mapped[int | None] = mapped_column(Integer)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_processed_rule_version_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramMessageRevision(Base):
    __tablename__ = "telegram_message_revisions"
    __table_args__ = (
        UniqueConstraint("message_id", "revision_no", name="uq_revision_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("telegram_messages.id"), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"
    __table_args__ = (UniqueConstraint("group_key", name="uq_duplicate_group_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageDuplicate(Base):
    __tablename__ = "message_duplicates"

    duplicate_message_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_messages.id"), primary_key=True
    )
    duplicate_group_id: Mapped[int] = mapped_column(
        ForeignKey("duplicate_groups.id"), nullable=False
    )
    canonical_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="exact_normalized_hash")
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
        UniqueConstraint(
            "revision_id", "rule_set_version_id", name="uq_detection_revision_rules"
        ),
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


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("canonical_message_id", name="uq_lead_canonical_message"),
    )

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


