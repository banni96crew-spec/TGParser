from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from telegram_lead_discovery.storage.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from telegram_lead_discovery.storage.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
