"""Temporary public targets for manual history scans.

Revision ID: 012_history_scan_manual_targets
Revises: 011_history_scan_v1
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_history_scan_manual_targets"
down_revision: str | None = "011_history_scan_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    target_columns = {column["name"] for column in inspector.get_columns("history_scan_targets")}
    if "ordinal" in target_columns:
        return
    with op.batch_alter_table("history_scan_sessions") as batch:
        batch.add_column(
            sa.Column("input_rejections_json", sa.Text(), nullable=False, server_default="[]")
        )
    with op.batch_alter_table("history_scan_targets") as batch:
        batch.drop_constraint("uq_history_scan_target_source", type_="unique")
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("origin", sa.String(length=16), nullable=False, server_default="monitoring")
        )
        batch.add_column(sa.Column("manual_reference", sa.String(length=512), nullable=True))
    op.execute(
        """
        UPDATE history_scan_targets AS current
        SET ordinal = (
            SELECT COUNT(*) FROM history_scan_targets AS earlier
            WHERE earlier.session_id = current.session_id AND earlier.id <= current.id
        )
        """
    )
    with op.batch_alter_table("history_scan_targets") as batch:
        batch.create_unique_constraint("uq_history_scan_target_ordinal", ["session_id", "ordinal"])
    with op.batch_alter_table("history_scan_results") as batch:
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    manual_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM history_scan_targets "
            "WHERE origin = 'manual' OR source_id IS NULL"
        )
    ).scalar_one()
    if manual_count:
        raise RuntimeError("manual_history_scan_rows_block_downgrade")
    with op.batch_alter_table("history_scan_results") as batch:
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("history_scan_targets") as batch:
        batch.drop_constraint("uq_history_scan_target_ordinal", type_="unique")
        batch.drop_column("manual_reference")
        batch.drop_column("origin")
        batch.drop_column("ordinal")
        batch.alter_column("source_id", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_history_scan_target_source", ["session_id", "source_id"])
    with op.batch_alter_table("history_scan_sessions") as batch:
        batch.drop_column("input_rejections_json")
