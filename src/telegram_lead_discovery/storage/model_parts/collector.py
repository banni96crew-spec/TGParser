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
    __table_args__ = (UniqueConstraint("message_id", "revision_no", name="uq_revision_no"),)

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
