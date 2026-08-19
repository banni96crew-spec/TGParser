"""Graph request control and discovery-mode exclusion (D-071).

Revision ID: 007_graph_request_control
Revises: 006_active_client_chat_v1
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "007_graph_request_control"
down_revision: str | None = "006_active_client_chat_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_discovery_runs_one_active_telegram"
_ACTIVE_PREDICATE = (
    "run_type IN ('graph','keyword_scouting') AND "
    "state IN ('queued','running','retry_wait_flood','cancelling')"
)


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _active_conflicts() -> list[int]:
    if "discovery_runs" not in _tables():
        return []
    rows = op.get_bind().execute(
        text(
            "SELECT id FROM discovery_runs WHERE "
            + _ACTIVE_PREDICATE
            + " ORDER BY id"
        )
    )
    return [int(row[0]) for row in rows]


def _index_exists() -> bool:
    if "discovery_runs" not in _tables():
        return False
    row = op.get_bind().execute(
        text(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"
        ),
        {"name": _INDEX},
    ).fetchone()
    return row is not None


def upgrade() -> None:
    conflicts = _active_conflicts()
    if len(conflicts) > 1:
        joined = ",".join(str(item) for item in conflicts)
        raise RuntimeError(f"active_telegram_discovery_conflict:{joined}")

    if "telegram_sources" in _tables() and "access_hash" not in _columns(
        "telegram_sources"
    ):
        op.add_column(
            "telegram_sources",
            sa.Column("access_hash", sa.Integer(), nullable=True),
        )
    if "discovery_runs" in _tables() and not _index_exists():
        op.execute(
            text(
                f"CREATE UNIQUE INDEX {_INDEX} ON discovery_runs (1) "
                f"WHERE {_ACTIVE_PREDICATE}"
            )
        )


def downgrade() -> None:
    if _index_exists():
        op.drop_index(_INDEX, table_name="discovery_runs")
    if "telegram_sources" in _tables() and "access_hash" in _columns(
        "telegram_sources"
    ):
        op.drop_column("telegram_sources", "access_hash")
