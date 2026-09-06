"""Keyword profile v8 empty directory + groups (D-074 / STO-024).

Revision ID: 010_keyword_profile_v8
Revises: 009_presented_suppress_class
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from telegram_lead_discovery.storage.alembic_data.keyword_profile_v8 import (
    downgrade_profile,
    upgrade_profile,
)

revision: str = "010_keyword_profile_v8"
down_revision: str | None = "009_presented_suppress_class"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    upgrade_profile(op.get_bind())


def downgrade() -> None:
    downgrade_profile(op.get_bind())
