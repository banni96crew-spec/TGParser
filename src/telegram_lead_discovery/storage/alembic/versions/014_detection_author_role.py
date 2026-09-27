"""Persist the immutable v7 author-role explanation (D-082 / STO-029)."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_detection_author_role"
down_revision: str | None = "013_account_request_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


_STATE_TABLE = "migration_014_detection_author_role_state"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _STATE_TABLE not in set(inspector.get_table_names()):
        op.create_table(
            _STATE_TABLE,
            sa.Column("table_name", sa.String(length=64), primary_key=True),
            sa.Column("added_author_role", sa.Boolean(), nullable=False),
            sa.Column("added_rule_ids", sa.Boolean(), nullable=False),
        )
    for table in ("processing_results", "history_scan_results"):
        columns = _columns(table)
        added_author_role = "author_role" not in columns
        added_rule_ids = "author_role_rule_ids_json" not in columns
        if added_author_role:
            op.add_column(
                table,
                sa.Column(
                    "author_role",
                    sa.String(length=32),
                    nullable=False,
                    server_default="legacy",
                ),
            )
        if added_rule_ids:
            op.add_column(
                table,
                sa.Column(
                    "author_role_rule_ids_json",
                    sa.Text(),
                    nullable=False,
                    server_default="[]",
                ),
            )
        bind.execute(
            sa.text(
                f"INSERT INTO {_STATE_TABLE} "
                "(table_name, added_author_role, added_rule_ids) "
                "VALUES (:table_name, :added_author_role, :added_rule_ids)"
            ),
            {
                "table_name": table,
                "added_author_role": added_author_role,
                "added_rule_ids": added_rule_ids,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    state_rows = {}
    if _STATE_TABLE in set(sa.inspect(bind).get_table_names()):
        state_rows = {
            row.table_name: row
            for row in bind.execute(
                sa.text(
                    f"SELECT table_name, added_author_role, added_rule_ids FROM {_STATE_TABLE}"
                )
            )
        }
    for table in ("history_scan_results", "processing_results"):
        columns = _columns(table)
        state = state_rows.get(table)
        with op.batch_alter_table(table) as batch:
            if (
                state is not None
                and state.added_rule_ids
                and "author_role_rule_ids_json" in columns
            ):
                batch.drop_column("author_role_rule_ids_json")
            if state is not None and state.added_author_role and "author_role" in columns:
                batch.drop_column("author_role")
    if _STATE_TABLE in set(sa.inspect(bind).get_table_names()):
        op.drop_table(_STATE_TABLE)
