from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from telegram_lead_discovery.storage.model_parts.base import Base, utcnow


class GraphDiscoveryPost(Base):
    """Durable raw post received by one bounded graph-history request."""

    __tablename__ = "graph_discovery_posts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_telegram_id",
            "telegram_message_id",
            name="uq_graph_post_run_source_message",
        ),
        Index("ix_graph_posts_run_source", "run_id", "source_telegram_id"),
        Index("ix_graph_posts_created_at", "created_at"),
        CheckConstraint(
            "author_key IS NULL OR length(author_key) = 64",
            name="ck_graph_posts_author_key",
        ),
        CheckConstraint(
            "author_kind IN ('user','bot','channel','anonymous','unknown')",
            name="ck_graph_posts_author_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_sources.id", ondelete="SET NULL")
    )
    parent_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_sources.id", ondelete="SET NULL")
    )
    source_telegram_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_username: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(512))
    request_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_key: Mapped[str | None] = mapped_column(String(64))
    author_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    permalink: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
