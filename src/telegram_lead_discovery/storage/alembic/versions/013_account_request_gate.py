"""Account-wide Telegram RPC start reservations (D-081 / STO-028)."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_account_request_gate"
down_revision: str | None = "012_history_scan_manual_targets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "telegram_account_request_gate" not in tables:
        op.create_table(
            "telegram_account_request_gate",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("next_allowed_at", sa.DateTime(timezone=True)),
            sa.Column("flood_wait_until", sa.DateTime(timezone=True)),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("id = 1", name="ck_telegram_account_request_gate_singleton"),
        )
        op.execute("INSERT INTO telegram_account_request_gate "
                   "(id, last_observed_at, version, updated_at) "
                   "VALUES (1, CURRENT_TIMESTAMP, 0, CURRENT_TIMESTAMP)")
    if "telegram_account_request_reservations" not in tables:
        op.create_table(
            "telegram_account_request_reservations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "purpose IN ('session_start','manual_resolve','history_scan',"
                "'collector','keyword','graph','live_service')",
                name="ck_telegram_account_request_purpose",
            ),
        )
        op.create_index(
            "ix_telegram_account_request_reservations_reserved_at",
            "telegram_account_request_reservations",
            ["reserved_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    active = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM jobs WHERE state IN "
            "('queued','running','retry_wait','retry_wait_flood') "
            "AND job_type IN ('collect','history_scan','discovery')"
        )
    ).scalar_one()
    flood = bind.execute(
        sa.text("SELECT flood_wait_until FROM telegram_account_request_gate WHERE id=1")
    ).scalar_one_or_none()
    if active or flood is not None:
        raise RuntimeError("telegram_account_request_gate_active_downgrade")
    op.drop_table("telegram_account_request_reservations")
    op.drop_table("telegram_account_request_gate")
