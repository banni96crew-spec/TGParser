"""Durable graph history results (D-072).

Revision ID: 008_graph_result_persistence
Revises: 007_graph_request_control
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "008_graph_result_persistence"
down_revision: str | None = "007_graph_request_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "graph_discovery_posts" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "graph_discovery_posts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("telegram_sources.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "parent_source_id",
            sa.Integer(),
            sa.ForeignKey("telegram_sources.id", ondelete="SET NULL"),
        ),
        sa.Column("source_telegram_id", sa.Integer(), nullable=False),
        sa.Column("source_username", sa.String(length=64)),
        sa.Column("source_url", sa.String(length=512)),
        sa.Column("request_ordinal", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_key", sa.String(length=64)),
        sa.Column("author_kind", sa.String(length=16), nullable=False),
        sa.Column("permalink", sa.String(length=512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "author_key IS NULL OR length(author_key) = 64",
            name="ck_graph_posts_author_key",
        ),
        sa.CheckConstraint(
            "author_kind IN ('user','bot','channel','anonymous','unknown')",
            name="ck_graph_posts_author_kind",
        ),
        sa.UniqueConstraint(
            "run_id",
            "source_telegram_id",
            "telegram_message_id",
            name="uq_graph_post_run_source_message",
        ),
    )
    op.create_index(
        "ix_graph_posts_run_source",
        "graph_discovery_posts",
        ["run_id", "source_telegram_id"],
    )
    op.create_index(
        "ix_graph_posts_created_at",
        "graph_discovery_posts",
        ["created_at"],
    )


def downgrade() -> None:
    if "graph_discovery_posts" in inspect(op.get_bind()).get_table_names():
        op.drop_table("graph_discovery_posts")
