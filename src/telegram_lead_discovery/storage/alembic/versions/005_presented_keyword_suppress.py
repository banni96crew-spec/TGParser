"""Durable presented-source suppress for keyword discovery (STO-020 / SRC-041/050 / D-069).

Revision ID: 005_presented_keyword_suppress
Revises: 004_opportunity_truth_status

Creates presented suppress ledger and idempotently backfills from historical
opportunity snapshots. Retention MUST NOT purge these rows.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "005_presented_keyword_suppress"
down_revision: str | None = "004_opportunity_truth_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _unique_constraint_names(table: str) -> set[str]:
    bind = op.get_bind()
    insp = inspect(bind)
    names: set[str] = set()
    for uc in insp.get_unique_constraints(table):
        if uc.get("name"):
            names.add(uc["name"])
    for idx in insp.get_indexes(table):
        if idx.get("unique") and idx.get("name"):
            names.add(idx["name"])
    return names


def _normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    text_value = str(username).strip().lstrip("@").casefold()
    return text_value or None


def _peer_key(telegram_id: int) -> str:
    return f"peer:{int(telegram_id)}"


def _create_presented_keyword_sources() -> None:
    op.create_table(
        "presented_keyword_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_key", sa.String(length=96), nullable=False),
        sa.Column("source_telegram_id", sa.Integer(), nullable=True),
        sa.Column("username_normalized", sa.String(length=64), nullable=True),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("origin_run_id", sa.Integer(), nullable=True),
        sa.Column("origin_opportunity_id", sa.Integer(), nullable=True),
        sa.Column("first_presented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_key",
            name="uq_presented_keyword_sources_canonical_key",
        ),
        sa.UniqueConstraint(
            "source_telegram_id",
            name="uq_presented_keyword_source_telegram_id",
        ),
    )
    op.create_index(
        "ix_presented_keyword_sources_username",
        "presented_keyword_sources",
        ["username_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_presented_keyword_sources_first_presented_at",
        "presented_keyword_sources",
        ["first_presented_at"],
        unique=False,
    )


def _backfill_from_opportunities() -> None:
    bind = op.get_bind()
    if "source_opportunity_snapshots" not in _table_names():
        return
    now = datetime.now(UTC)
    rows = bind.execute(
        text(
            """
            SELECT id, run_id, source_telegram_id, username, created_at
            FROM source_opportunity_snapshots
            ORDER BY id ASC
            """
        )
    ).fetchall()
    for row in rows:
        opp_id, run_id, tid, username, created_at = row
        if tid is None:
            continue
        tid_i = int(tid)
        canonical = _peer_key(tid_i)
        uname = _normalize_username(username)
        presented_at = created_at or now
        existing = bind.execute(
            text(
                "SELECT id FROM presented_keyword_sources WHERE canonical_key = :ck OR source_telegram_id = :tid"
            ),
            {"ck": canonical, "tid": tid_i},
        ).fetchone()
        if existing is not None:
            continue
        aliases = json.dumps([uname] if uname else [], ensure_ascii=False)
        bind.execute(
            text(
                """
                INSERT INTO presented_keyword_sources (
                    canonical_key, source_telegram_id, username_normalized, aliases_json,
                    origin_run_id, origin_opportunity_id, first_presented_at, version,
                    created_at, updated_at
                ) VALUES (
                    :ck, :tid, :uname, :aliases, :run_id, :opp_id, :presented_at, 1, :now, :now
                )
                """
            ),
            {
                "ck": canonical,
                "tid": tid_i,
                "uname": uname,
                "aliases": aliases,
                "run_id": run_id,
                "opp_id": opp_id,
                "presented_at": presented_at,
                "now": now,
            },
        )


def upgrade() -> None:
    if "presented_keyword_sources" not in _table_names():
        _create_presented_keyword_sources()
    else:
        uniques = _unique_constraint_names("presented_keyword_sources")
        indexes = _index_names("presented_keyword_sources")
        if "uq_presented_keyword_sources_canonical_key" not in uniques:
            op.create_unique_constraint(
                "uq_presented_keyword_sources_canonical_key",
                "presented_keyword_sources",
                ["canonical_key"],
            )
        if "uq_presented_keyword_source_telegram_id" not in uniques:
            op.create_unique_constraint(
                "uq_presented_keyword_source_telegram_id",
                "presented_keyword_sources",
                ["source_telegram_id"],
            )
        if "ix_presented_keyword_sources_username" not in indexes:
            op.create_index(
                "ix_presented_keyword_sources_username",
                "presented_keyword_sources",
                ["username_normalized"],
                unique=False,
            )
        if "ix_presented_keyword_sources_first_presented_at" not in indexes:
            op.create_index(
                "ix_presented_keyword_sources_first_presented_at",
                "presented_keyword_sources",
                ["first_presented_at"],
                unique=False,
            )
    _backfill_from_opportunities()


def downgrade() -> None:
    if "presented_keyword_sources" in _table_names():
        op.drop_table("presented_keyword_sources")
