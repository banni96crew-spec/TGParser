"""Add opportunity truth_status + evidence matched_rule_ids (STO-019 / D-068).

Revision ID: 004_opportunity_truth_status
Revises: 003_dismissed_keyword_suppress

Extends unapplied 004 (live head remains 003): truth columns on
``source_opportunity_snapshots`` and ``matched_rule_ids_json`` on
``source_discovery_evidence`` (default ``[]`` for existing rows).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "004_opportunity_truth_status"
down_revision: str | None = "003_dismissed_keyword_suppress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    opp = "source_opportunity_snapshots"
    cols = _column_names(opp)
    if "truth_status" not in cols:
        op.add_column(
            opp,
            sa.Column(
                "truth_status",
                sa.String(length=16),
                nullable=False,
                server_default="inconclusive",
            ),
        )
    if "verification_scanned_count" not in cols:
        op.add_column(
            opp,
            sa.Column(
                "verification_scanned_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "verification_stop_reason" not in cols:
        op.add_column(
            opp,
            sa.Column("verification_stop_reason", sa.String(length=64), nullable=True),
        )

    evidence = "source_discovery_evidence"
    ev_cols = _column_names(evidence)
    if "matched_rule_ids_json" not in ev_cols:
        op.add_column(
            evidence,
            sa.Column(
                "matched_rule_ids_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    evidence = "source_discovery_evidence"
    ev_cols = _column_names(evidence)
    if "matched_rule_ids_json" in ev_cols:
        op.drop_column(evidence, "matched_rule_ids_json")

    opp = "source_opportunity_snapshots"
    cols = _column_names(opp)
    if "verification_stop_reason" in cols:
        op.drop_column(opp, "verification_stop_reason")
    if "verification_scanned_count" in cols:
        op.drop_column(opp, "verification_scanned_count")
    if "truth_status" in cols:
        op.drop_column(opp, "truth_status")
