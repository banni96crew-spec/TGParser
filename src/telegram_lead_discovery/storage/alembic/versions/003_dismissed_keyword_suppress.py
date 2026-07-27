"""Durable dismiss suppress for keyword discovery (STO-016 / SRC-032).

Revision ID: 003_dismissed_keyword_suppress
Revises: 002_keyword_source_discovery
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "003_dismissed_keyword_suppress"
down_revision: str | None = "002_keyword_source_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _create_dismissed_keyword_sources() -> None:
    op.create_table(
        "dismissed_keyword_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_telegram_id", sa.Integer(), nullable=False),
        sa.Column("username_normalized", sa.String(length=64), nullable=True),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("dismiss_reason", sa.String(length=512), nullable=True),
        sa.Column("origin_run_id", sa.Integer(), nullable=True),
        sa.Column("origin_opportunity_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_telegram_id",
            name="uq_dismissed_keyword_source_telegram_id",
        ),
    )
    op.create_index(
        "ix_dismissed_keyword_sources_username",
        "dismissed_keyword_sources",
        ["username_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_dismissed_keyword_sources_created_at",
        "dismissed_keyword_sources",
        ["created_at"],
        unique=False,
    )


def upgrade() -> None:
    names = _table_names()
    if "dismissed_keyword_sources" not in names:
        _create_dismissed_keyword_sources()
        return
    indexes = _index_names("dismissed_keyword_sources")
    if "ix_dismissed_keyword_sources_username" not in indexes:
        op.create_index(
            "ix_dismissed_keyword_sources_username",
            "dismissed_keyword_sources",
            ["username_normalized"],
            unique=False,
        )
    if "ix_dismissed_keyword_sources_created_at" not in indexes:
        op.create_index(
            "ix_dismissed_keyword_sources_created_at",
            "dismissed_keyword_sources",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    if "dismissed_keyword_sources" in _table_names():
        op.drop_table("dismissed_keyword_sources")
