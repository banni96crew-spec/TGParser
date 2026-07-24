"""Keyword source discovery schema (STO-015).

Revision ID: 002_keyword_source_discovery
Revises: 001_initial

Creates keyword scouting tables and nullable extensions on discovery_runs.
Idempotent relative to 001_initial create_all (which uses current metadata).
Does not rewrite existing discovery run rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision: str = "002_keyword_source_discovery"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_DISCOVERY_RUN_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    (
        "run_type",
        sa.Column("run_type", sa.String(length=32), nullable=False, server_default="graph"),
    ),
    ("profile_version_id", sa.Column("profile_version_id", sa.Integer(), nullable=True)),
    ("search_mode", sa.Column("search_mode", sa.String(length=32), nullable=True)),
    ("rule_set_version_id", sa.Column("rule_set_version_id", sa.Integer(), nullable=True)),
    ("rule_set_checksum", sa.Column("rule_set_checksum", sa.String(length=64), nullable=True)),
    ("phase", sa.Column("phase", sa.String(length=32), nullable=True)),
    ("quota_snapshot_json", sa.Column("quota_snapshot_json", sa.Text(), nullable=True)),
    ("cursor_json", sa.Column("cursor_json", sa.Text(), nullable=True)),
    ("last_error_code", sa.Column("last_error_code", sa.String(length=64), nullable=True)),
    ("version", sa.Column("version", sa.Integer(), nullable=False, server_default="1")),
)


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _index_names(table: str) -> set[str]:
    return {idx["name"] for idx in inspect(op.get_bind()).get_indexes(table)}


def _create_profiles() -> None:
    op.create_table(
        "keyword_discovery_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_keyword_discovery_profile_name"),
    )


def _create_profile_versions() -> None:
    op.create_table(
        "keyword_discovery_profile_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("post_queries_json", sa.Text(), nullable=False),
        sa.Column("directory_queries_json", sa.Text(), nullable=False),
        sa.Column("required_service_profiles_json", sa.Text(), nullable=False),
        sa.Column("additional_exclusions_json", sa.Text(), nullable=False),
        sa.Column("source_scope", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["keyword_discovery_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "version", name="uq_keyword_profile_id_version"),
    )


def _create_run_queries() -> None:
    op.create_table(
        "discovery_run_queries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query_kind", sa.String(length=32), nullable=False),
        sa.Column("query_text", sa.String(length=128), nullable=False),
        sa.Column("source_telegram_id", sa.Integer(), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("cursor_json", sa.Text(), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_discovery_run_query_ordinal"),
    )
    op.create_index(
        "ix_discovery_run_queries_run_state",
        "discovery_run_queries",
        ["run_id", "state"],
        unique=False,
    )


def _create_evidence() -> None:
    op.create_table(
        "source_discovery_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_telegram_id", sa.Integer(), nullable=False),
        sa.Column("source_username", sa.String(length=64), nullable=True),
        sa.Column("source_title", sa.String(length=256), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("permalink", sa.String(length=512), nullable=True),
        sa.Column("excerpt", sa.String(length=240), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("matched_query_ordinals_json", sa.Text(), nullable=False),
        sa.Column("discovery_channels_json", sa.Text(), nullable=False),
        sa.Column("detection_category", sa.String(length=64), nullable=False),
        sa.Column("is_qualified", sa.Boolean(), nullable=False),
        sa.Column("hard_exclusion", sa.Boolean(), nullable=False),
        sa.Column("hard_exclusion_rule_id", sa.String(length=64), nullable=True),
        sa.Column("service_profiles_json", sa.Text(), nullable=False),
        sa.Column("rule_set_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "source_telegram_id",
            "telegram_message_id",
            name="uq_evidence_run_source_message",
        ),
    )
    op.create_index(
        "ix_evidence_run_source_telegram_id",
        "source_discovery_evidence",
        ["run_id", "source_telegram_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_discovery_evidence_created_at",
        "source_discovery_evidence",
        ["created_at"],
        unique=False,
    )


def _create_opportunity_snapshots() -> None:
    op.create_table(
        "source_opportunity_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_telegram_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("public_url", sa.String(length=512), nullable=True),
        sa.Column("linked_parent_telegram_id", sa.Integer(), nullable=True),
        sa.Column("qualified_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("active_week_count", sa.Integer(), nullable=False),
        sa.Column("ecommerce_qualified_count", sa.Integer(), nullable=False),
        sa.Column("last_qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_message_count", sa.Integer(), nullable=False),
        sa.Column("sample_timestamps", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("band", sa.String(length=16), nullable=False),
        sa.Column("score_components_json", sa.Text(), nullable=False),
        sa.Column("discovery_channels_json", sa.Text(), nullable=False),
        sa.Column("review_state", sa.String(length=16), nullable=False),
        sa.Column("promoted_source_id", sa.Integer(), nullable=True),
        sa.Column("dismiss_reason", sa.String(length=512), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_opportunity_score_0_100"),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["telegram_sources.id"]),
        sa.ForeignKeyConstraint(["promoted_source_id"], ["telegram_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "source_telegram_id",
            name="uq_opportunity_run_source_telegram_id",
        ),
    )
    op.create_index(
        "ix_opportunity_run_score_desc",
        "source_opportunity_snapshots",
        ["run_id", text("score DESC")],
        unique=False,
    )
    op.create_index(
        "ix_source_opportunity_snapshots_created_at",
        "source_opportunity_snapshots",
        ["created_at"],
        unique=False,
    )


def _has_profile_version_fk() -> bool:
    return any(
        fk.get("referred_table") == "keyword_discovery_profile_versions"
        for fk in inspect(op.get_bind()).get_foreign_keys("discovery_runs")
    )


def _extend_discovery_runs() -> None:
    existing = _column_names("discovery_runs")
    missing = [col for name, col in _NEW_DISCOVERY_RUN_COLUMNS if name not in existing]
    root_nullable = True
    if "root_source_ids_json" in existing:
        root_meta = next(
            c
            for c in inspect(op.get_bind()).get_columns("discovery_runs")
            if c["name"] == "root_source_ids_json"
        )
        root_nullable = bool(root_meta.get("nullable"))

    if missing or not root_nullable:
        with op.batch_alter_table("discovery_runs") as batch_op:
            for col in missing:
                batch_op.add_column(col)
            if not root_nullable:
                batch_op.alter_column(
                    "root_source_ids_json",
                    existing_type=sa.Text(),
                    nullable=True,
                )

    if (
        "profile_version_id" in _column_names("discovery_runs")
        and "keyword_discovery_profile_versions" in _table_names()
        and not _has_profile_version_fk()
    ):
        with op.batch_alter_table("discovery_runs") as batch_op:
            batch_op.create_foreign_key(
                "fk_discovery_runs_profile_version_id",
                "keyword_discovery_profile_versions",
                ["profile_version_id"],
                ["id"],
            )


def _ensure_indexes() -> None:
    if "discovery_run_queries" in _table_names():
        indexes = _index_names("discovery_run_queries")
        if "ix_discovery_run_queries_run_state" not in indexes:
            op.create_index(
                "ix_discovery_run_queries_run_state",
                "discovery_run_queries",
                ["run_id", "state"],
                unique=False,
            )
    if "source_discovery_evidence" in _table_names():
        indexes = _index_names("source_discovery_evidence")
        if "ix_evidence_run_source_telegram_id" not in indexes:
            op.create_index(
                "ix_evidence_run_source_telegram_id",
                "source_discovery_evidence",
                ["run_id", "source_telegram_id"],
                unique=False,
            )
        if "ix_source_discovery_evidence_created_at" not in indexes:
            op.create_index(
                "ix_source_discovery_evidence_created_at",
                "source_discovery_evidence",
                ["created_at"],
                unique=False,
            )
    if "source_opportunity_snapshots" in _table_names():
        indexes = _index_names("source_opportunity_snapshots")
        if "ix_opportunity_run_score_desc" not in indexes:
            op.create_index(
                "ix_opportunity_run_score_desc",
                "source_opportunity_snapshots",
                ["run_id", text("score DESC")],
                unique=False,
            )
        if "ix_source_opportunity_snapshots_created_at" not in indexes:
            op.create_index(
                "ix_source_opportunity_snapshots_created_at",
                "source_opportunity_snapshots",
                ["created_at"],
                unique=False,
            )


def upgrade() -> None:
    names = _table_names()
    if "keyword_discovery_profiles" not in names:
        _create_profiles()
    if "keyword_discovery_profile_versions" not in names:
        _create_profile_versions()
    _extend_discovery_runs()
    names = _table_names()
    if "discovery_run_queries" not in names:
        _create_run_queries()
    if "source_discovery_evidence" not in names:
        _create_evidence()
    if "source_opportunity_snapshots" not in names:
        _create_opportunity_snapshots()
    _ensure_indexes()

    # Drop server defaults after backfill so ORM defaults remain authoritative.
    with op.batch_alter_table("discovery_runs") as batch_op:
        cols = _column_names("discovery_runs")
        if "run_type" in cols:
            batch_op.alter_column("run_type", server_default=None, existing_type=sa.String(32))
        if "version" in cols:
            batch_op.alter_column("version", server_default=None, existing_type=sa.Integer())


def downgrade() -> None:
    names = _table_names()
    if "source_opportunity_snapshots" in names:
        op.drop_table("source_opportunity_snapshots")
    if "source_discovery_evidence" in names:
        op.drop_table("source_discovery_evidence")
    if "discovery_run_queries" in names:
        op.drop_table("discovery_run_queries")

    if "discovery_runs" in names:
        cols = _column_names("discovery_runs")
        drop_cols = [name for name, _ in _NEW_DISCOVERY_RUN_COLUMNS if name in cols]
        op.execute(
            text(
                "UPDATE discovery_runs SET root_source_ids_json = '[]' "
                "WHERE root_source_ids_json IS NULL"
            )
        )
        with op.batch_alter_table("discovery_runs") as batch_op:
            fk_names = [
                fk.get("name")
                for fk in inspect(op.get_bind()).get_foreign_keys("discovery_runs")
                if fk.get("referred_table") == "keyword_discovery_profile_versions"
            ]
            for fk_name in fk_names:
                if fk_name:
                    batch_op.drop_constraint(fk_name, type_="foreignkey")
            for name in drop_cols:
                batch_op.drop_column(name)
            if "root_source_ids_json" in cols:
                batch_op.alter_column(
                    "root_source_ids_json",
                    existing_type=sa.Text(),
                    nullable=False,
                )

    names = _table_names()
    if "keyword_discovery_profile_versions" in names:
        op.drop_table("keyword_discovery_profile_versions")
    if "keyword_discovery_profiles" in names:
        op.drop_table("keyword_discovery_profiles")
