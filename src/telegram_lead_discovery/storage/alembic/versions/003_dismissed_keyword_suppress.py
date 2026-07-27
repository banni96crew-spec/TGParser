"""Durable dismiss suppress for keyword discovery (STO-017 / SRC-032..035).

Revision ID: 003_dismissed_keyword_suppress
Revises: 002_keyword_source_discovery

Creates/extends dismiss suppress ledger with canonical_key, nullable peer id,
and idempotent historical backfill from dismissed opportunity snapshots.
Idempotent relative to 001_initial create_all (current metadata).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "003_dismissed_keyword_suppress"
down_revision: str | None = "002_keyword_source_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _unique_constraint_names(table: str) -> set[str]:
    bind = op.get_bind()
    insp = inspect(bind)
    names: set[str] = set()
    for uc in insp.get_unique_constraints(table):
        if uc.get("name"):
            names.add(uc["name"])
    # SQLite often surfaces UNIQUE indexes instead of named constraints.
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


def _create_dismissed_keyword_sources() -> None:
    op.create_table(
        "dismissed_keyword_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_key", sa.String(length=96), nullable=False),
        sa.Column("source_telegram_id", sa.Integer(), nullable=True),
        sa.Column("username_normalized", sa.String(length=64), nullable=True),
        sa.Column("aliases_json", sa.Text(), nullable=False),
        sa.Column("dismiss_reason", sa.String(length=512), nullable=True),
        sa.Column("origin_run_id", sa.Integer(), nullable=True),
        sa.Column("origin_opportunity_id", sa.Integer(), nullable=True),
        sa.Column("operator_trigger", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_key",
            name="uq_dismissed_keyword_sources_canonical_key",
        ),
        sa.UniqueConstraint(
            "source_telegram_id",
            name="uq_dismissed_keyword_source_telegram_id",
        ),
    )
    op.create_index(
        "ix_dismissed_keyword_sources_username",
        "dismissed_keyword_sources",
        ["username_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_dismissed_keyword_sources_created_at",
        "dismissed_keyword_sources",
        ["created_at"],
        unique=False,
    )


def _create_reconsider_audit_table() -> None:
    op.create_table(
        "dismiss_suppress_reconsidered_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.String(length=96), nullable=True),
        sa.Column("suppress_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            name="uq_dismiss_suppress_reconsidered_event_id",
        ),
    )
    op.create_index(
        "ix_dismiss_suppress_reconsidered_occurred_at",
        "dismiss_suppress_reconsidered_events",
        ["occurred_at"],
        unique=False,
    )


def _ensure_dismissed_schema() -> None:
    """Add Wave-02 columns/constraints when table already exists (create_all / Wave-01)."""
    cols = _column_names("dismissed_keyword_sources")
    if "canonical_key" not in cols:
        op.add_column(
            "dismissed_keyword_sources",
            sa.Column("canonical_key", sa.String(length=96), nullable=True),
        )
    if "operator_trigger" not in cols:
        op.add_column(
            "dismissed_keyword_sources",
            sa.Column("operator_trigger", sa.String(length=64), nullable=True),
        )
    if "version" not in cols:
        op.add_column(
            "dismissed_keyword_sources",
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )

    # Provisional identity requires nullable peer id (SRC-034).
    bind = op.get_bind()
    tid_col = next(
        c for c in inspect(bind).get_columns("dismissed_keyword_sources")
        if c["name"] == "source_telegram_id"
    )
    if tid_col.get("nullable") is False:
        with op.batch_alter_table("dismissed_keyword_sources") as batch:
            batch.alter_column(
                "source_telegram_id",
                existing_type=sa.Integer(),
                nullable=True,
            )

    # Backfill missing keys from existing peer rows before enforcing NOT NULL / unique.
    bind.execute(
        text(
            """
            UPDATE dismissed_keyword_sources
            SET canonical_key = 'peer:' || CAST(source_telegram_id AS TEXT)
            WHERE (canonical_key IS NULL OR canonical_key = '')
              AND source_telegram_id IS NOT NULL
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE dismissed_keyword_sources
            SET canonical_key = 'username:' || lower(username_normalized)
            WHERE (canonical_key IS NULL OR canonical_key = '')
              AND username_normalized IS NOT NULL
              AND username_normalized != ''
            """
        )
    )

    cols = _column_names("dismissed_keyword_sources")
    # Enforce NOT NULL on canonical_key when all rows are populated.
    null_keys = bind.execute(
        text(
            """
            SELECT COUNT(*) FROM dismissed_keyword_sources
            WHERE canonical_key IS NULL OR canonical_key = ''
            """
        )
    ).scalar()
    if int(null_keys or 0) == 0:
        ck = next(
            c
            for c in inspect(bind).get_columns("dismissed_keyword_sources")
            if c["name"] == "canonical_key"
        )
        if ck.get("nullable") is not False:
            with op.batch_alter_table("dismissed_keyword_sources") as batch:
                batch.alter_column(
                    "canonical_key",
                    existing_type=sa.String(length=96),
                    nullable=False,
                )

    uniques = _unique_constraint_names("dismissed_keyword_sources")
    if "uq_dismissed_keyword_sources_canonical_key" not in uniques:
        # SQLite: recreate unique via batch when constraint missing.
        with op.batch_alter_table("dismissed_keyword_sources") as batch:
            batch.create_unique_constraint(
                "uq_dismissed_keyword_sources_canonical_key",
                ["canonical_key"],
            )

    indexes = _index_names("dismissed_keyword_sources")
    if "ix_dismissed_keyword_sources_username" not in indexes:
        op.create_index(
            "ix_dismissed_keyword_sources_username",
            "dismissed_keyword_sources",
            ["username_normalized"],
            unique=False,
        )
    if "ix_dismissed_keyword_sources_created_at" not in indexes:
        op.create_index(
            "ix_dismissed_keyword_sources_created_at",
            "dismissed_keyword_sources",
            ["created_at"],
            unique=False,
        )


def _load_aliases(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if isinstance(item, str)]


def _backfill_from_dismissed_snapshots() -> None:
    """STO-017: every historical dismissed identity → ≥1 suppress row (idempotent)."""
    if "source_opportunity_snapshots" not in _table_names():
        return

    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT id, run_id, source_telegram_id, username, dismiss_reason,
                   created_at, updated_at
            FROM source_opportunity_snapshots
            WHERE review_state = 'dismissed'
              AND source_telegram_id IS NOT NULL
            ORDER BY id ASC
            """
        )
    ).fetchall()
    if not rows:
        return

    # Collapse rename/alias collisions by peer telegram id.
    by_peer: dict[int, dict] = {}
    for row in rows:
        snap_id = int(row[0])
        run_id = int(row[1]) if row[1] is not None else None
        tid = int(row[2])
        username = _normalize_username(row[3])
        reason = row[4]
        created_at = row[5]
        updated_at = row[6]
        entry = by_peer.get(tid)
        if entry is None:
            by_peer[tid] = {
                "canonical_key": _peer_key(tid),
                "source_telegram_id": tid,
                "username_normalized": username,
                "aliases": set(),
                "dismiss_reason": reason,
                "origin_run_id": run_id,
                "origin_opportunity_id": snap_id,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            continue
        if username:
            if entry["username_normalized"] is None:
                entry["username_normalized"] = username
            elif username != entry["username_normalized"]:
                entry["aliases"].add(username)
        if entry["dismiss_reason"] is None and reason is not None:
            entry["dismiss_reason"] = reason
        # Prefer earliest origin for provenance.
        if entry["origin_opportunity_id"] is None or snap_id < int(
            entry["origin_opportunity_id"]
        ):
            entry["origin_opportunity_id"] = snap_id
            entry["origin_run_id"] = run_id
        entry["updated_at"] = updated_at or entry["updated_at"]

    now = datetime.now(UTC).isoformat()
    for tid, entry in by_peer.items():
        existing = bind.execute(
            text(
                """
                SELECT id, username_normalized, aliases_json, dismiss_reason,
                       origin_run_id, origin_opportunity_id
                FROM dismissed_keyword_sources
                WHERE canonical_key = :ck
                   OR source_telegram_id = :tid
                LIMIT 1
                """
            ),
            {"ck": entry["canonical_key"], "tid": tid},
        ).fetchone()

        aliases = set(entry["aliases"])
        if existing is None:
            aliases_json = json.dumps(sorted(aliases), ensure_ascii=False)
            bind.execute(
                text(
                    """
                    INSERT INTO dismissed_keyword_sources (
                        canonical_key, source_telegram_id, username_normalized,
                        aliases_json, dismiss_reason, origin_run_id,
                        origin_opportunity_id, operator_trigger, version,
                        created_at, updated_at
                    ) VALUES (
                        :canonical_key, :source_telegram_id, :username_normalized,
                        :aliases_json, :dismiss_reason, :origin_run_id,
                        :origin_opportunity_id, :operator_trigger, 1,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    "canonical_key": entry["canonical_key"],
                    "source_telegram_id": tid,
                    "username_normalized": entry["username_normalized"],
                    "aliases_json": aliases_json,
                    "dismiss_reason": entry["dismiss_reason"],
                    "origin_run_id": entry["origin_run_id"],
                    "origin_opportunity_id": entry["origin_opportunity_id"],
                    "operator_trigger": "HistoricalMigrationBackfill",
                    "created_at": entry["created_at"] or now,
                    "updated_at": entry["updated_at"] or now,
                },
            )
            continue

        # Merge claim fields only; membership already present (idempotent).
        existing_aliases = set(_load_aliases(existing[2]))
        existing_user = existing[1]
        if entry["username_normalized"]:
            if existing_user is None:
                existing_user = entry["username_normalized"]
            elif entry["username_normalized"] != existing_user:
                existing_aliases.add(entry["username_normalized"])
        existing_aliases |= aliases
        if existing_user and existing_user in existing_aliases:
            existing_aliases.discard(existing_user)
        reason = existing[3] or entry["dismiss_reason"]
        origin_run = existing[4] or entry["origin_run_id"]
        origin_opp = existing[5] or entry["origin_opportunity_id"]
        bind.execute(
            text(
                """
                UPDATE dismissed_keyword_sources
                SET canonical_key = :canonical_key,
                    source_telegram_id = :tid,
                    username_normalized = :username_normalized,
                    aliases_json = :aliases_json,
                    dismiss_reason = :dismiss_reason,
                    origin_run_id = :origin_run_id,
                    origin_opportunity_id = :origin_opportunity_id,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ),
            {
                "id": int(existing[0]),
                "canonical_key": entry["canonical_key"],
                "tid": tid,
                "username_normalized": existing_user,
                "aliases_json": json.dumps(sorted(existing_aliases), ensure_ascii=False),
                "dismiss_reason": reason,
                "origin_run_id": origin_run,
                "origin_opportunity_id": origin_opp,
                "updated_at": entry["updated_at"] or now,
            },
        )


def upgrade() -> None:
    names = _table_names()
    if "dismissed_keyword_sources" not in names:
        _create_dismissed_keyword_sources()
    else:
        _ensure_dismissed_schema()

    if "dismiss_suppress_reconsidered_events" not in _table_names():
        _create_reconsider_audit_table()
    else:
        indexes = _index_names("dismiss_suppress_reconsidered_events")
        if "ix_dismiss_suppress_reconsidered_occurred_at" not in indexes:
            op.create_index(
                "ix_dismiss_suppress_reconsidered_occurred_at",
                "dismiss_suppress_reconsidered_events",
                ["occurred_at"],
                unique=False,
            )

    _backfill_from_dismissed_snapshots()


def downgrade() -> None:
    if "dismiss_suppress_reconsidered_events" in _table_names():
        op.drop_table("dismiss_suppress_reconsidered_events")
    if "dismissed_keyword_sources" in _table_names():
        op.drop_table("dismissed_keyword_sources")
