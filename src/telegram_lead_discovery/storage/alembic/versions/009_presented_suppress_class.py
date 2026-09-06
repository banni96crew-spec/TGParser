"""Presented suppress class (D-076 / STO-024).

Revision ID: 009_presented_suppress_class
Revises: 008_graph_result_persistence
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from telegram_lead_discovery.storage.alembic_data.presented_suppress_class import (
    LEGACY,
    backfill_from_live_snapshots,
)

revision: str = "009_presented_suppress_class"
down_revision: str | None = "008_graph_result_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "presented_keyword_sources"
_COLUMN = "suppress_class"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _TABLE in _tables() and _COLUMN not in _columns(_TABLE):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=32),
                nullable=False,
                server_default=LEGACY,
            ),
        )
    backfill_from_live_snapshots(op.get_bind())


def downgrade() -> None:
    if _TABLE in _tables() and _COLUMN in _columns(_TABLE):
        op.drop_column(_TABLE, _COLUMN)
