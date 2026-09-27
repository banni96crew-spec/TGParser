"""Manual multi-source history scan v1.

Revision ID: 011_history_scan_v1
Revises: 010_keyword_profile_v8
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_history_scan_v1"
down_revision: str | None = "010_keyword_profile_v8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 001 historically calls Base.metadata.create_all(). On a clean
    # install that already includes these current models, so only create the
    # tables when upgrading an existing database at revision 010.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "history_scan_sessions" in existing:
        return
    op.create_table(
        "history_scan_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("from_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_set_version_id", sa.Integer(), nullable=False),
        sa.Column("rule_set_checksum", sa.String(length=128), nullable=False),
        sa.Column("analysis_context_json", sa.Text(), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_set_version_id"], ["rule_set_versions.id"]),
    )
    op.create_table(
        "history_scan_targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("telegram_peer_id", sa.Integer()),
        sa.Column("access_hash", sa.Integer()),
        sa.Column("username_normalized", sa.String(length=64)),
        sa.Column("source_title", sa.String(length=256), nullable=False),
        sa.Column("source_quality_score", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("continuation_cursor", sa.String(length=64)),
        sa.Column("messages_scanned", sa.Integer(), nullable=False),
        sa.Column("results_found", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["history_scan_sessions.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["telegram_sources.id"]),
        sa.UniqueConstraint("session_id", "source_id", name="uq_history_scan_target_source"),
    )
    op.create_table(
        "history_scan_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("permalink", sa.String(length=512)),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("score_total", sa.Integer(), nullable=False),
        sa.Column("score_band", sa.String(length=32), nullable=False),
        sa.Column("explanation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["history_scan_sessions.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["history_scan_targets.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["telegram_sources.id"]),
        sa.UniqueConstraint(
            "target_id", "telegram_message_id", name="uq_history_scan_result_message"
        ),
    )
    op.create_index(
        "ix_history_scan_results_session_published",
        "history_scan_results",
        ["session_id", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_history_scan_results_session_published", table_name="history_scan_results")
    op.drop_table("history_scan_results")
    op.drop_table("history_scan_targets")
    op.drop_table("history_scan_sessions")
