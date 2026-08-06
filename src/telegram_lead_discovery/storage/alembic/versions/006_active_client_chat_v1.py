"""ActiveClientChat v1 storage and immutable terminal outcomes (D-070/STO-021).

Revision ID: 006_active_client_chat_v1
Revises: 005_presented_keyword_suppress
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

from telegram_lead_discovery.storage.alembic_data.active_client_chat_v1_profile import (
    ADDITIONAL_EXCLUSIONS,
    DIRECTORY_QUERIES,
    POST_QUERIES,
    REPLACEMENT_DIRECTORY_QUERIES,
    downgrade_seed_profile,
)

revision: str = "006_active_client_chat_v1"
down_revision: str | None = "005_presented_keyword_suppress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _add_columns(table: str, columns: tuple[sa.Column, ...]) -> None:
    existing = _columns(table)
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def _upgrade_runs() -> None:
    _add_columns(
        "discovery_runs",
        (
            sa.Column("reference_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("gate_status", sa.String(16), nullable=False, server_default="inconclusive"),
            sa.Column("pool_exhausted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("pool_exhausted_reason", sa.String(64), nullable=True),
            sa.Column("run_termination_reason", sa.String(64), nullable=True),
        ),
    )


def _upgrade_profile_versions() -> None:
    _add_columns(
        "keyword_discovery_profile_versions",
        (
            sa.Column(
                "replacement_directory_queries_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
        ),
    )


def _upgrade_evidence() -> None:
    _add_columns(
        "source_discovery_evidence",
        (
            sa.Column("author_key", sa.String(64), nullable=True),
            sa.Column("author_kind", sa.String(16), nullable=False, server_default="unknown"),
        ),
    )
    checks = {
        item.get("name")
        for item in inspect(op.get_bind()).get_check_constraints("source_discovery_evidence")
    }
    missing_key = "ck_source_discovery_evidence_author_key" not in checks
    missing_kind = "ck_source_discovery_evidence_author_kind" not in checks
    if missing_key or missing_kind:
        with op.batch_alter_table("source_discovery_evidence", recreate="always") as batch:
            if missing_key:
                batch.create_check_constraint(
                    "ck_source_discovery_evidence_author_key",
                    "author_key IS NULL OR length(author_key) = 64",
                )
            if missing_kind:
                batch.create_check_constraint(
                    "ck_source_discovery_evidence_author_kind",
                    "author_kind IN ('user','bot','channel','anonymous','unknown')",
                )


def _upgrade_snapshots() -> None:
    integer_columns = (
        "activity_message_count",
        "activity_active_day_count",
        "activity_distinct_author_count",
        "client_request_count",
        "client_request_author_count",
        "hard_excluded_count",
        "unknown_author_message_count",
    )
    columns: list[sa.Column] = [
        sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        for name in integer_columns
    ]
    columns.extend(
        (
            sa.Column("latest_client_request_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sample_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "qualification_version", sa.String(32), nullable=False, server_default="legacy"
            ),
            sa.Column("qualification_reasons_json", sa.Text(), nullable=False, server_default="[]"),
        )
    )
    _add_columns("source_opportunity_snapshots", tuple(columns))


def _create_terminal_outcomes() -> None:
    if "discovery_terminal_outcomes" in _tables():
        return
    op.create_table(
        "discovery_terminal_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("discovery_runs.id"), nullable=False),
        sa.Column("source_canonical_key", sa.String(96), nullable=False),
        sa.Column("terminal_outcome_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("truth_status", sa.String(16), nullable=False),
        sa.Column("verification_stop_reason", sa.String(64), nullable=False),
        sa.Column("activity_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activity_active_day_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "activity_distinct_author_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("client_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_request_author_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hard_excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_author_message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_client_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("threshold_activity_messages", sa.Boolean(), nullable=False),
        sa.Column("threshold_activity_days", sa.Boolean(), nullable=False),
        sa.Column("threshold_activity_authors", sa.Boolean(), nullable=False),
        sa.Column("threshold_client_requests", sa.Boolean(), nullable=False),
        sa.Column("threshold_client_authors", sa.Boolean(), nullable=False),
        sa.Column("threshold_freshness", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "truth_status IN ('quality','near','inconclusive','rejected')",
            name="ck_discovery_terminal_outcome_truth",
        ),
        sa.CheckConstraint(
            "verification_stop_reason IN "
            "('quality_reached','window_complete','history_exhausted','source_cap',"
            "'run_cap','inaccessible','cancelled')",
            name="ck_discovery_terminal_outcome_stop_reason",
        ),
        sa.UniqueConstraint(
            "run_id",
            "source_canonical_key",
            "terminal_outcome_version",
            name="uq_discovery_terminal_outcome_version",
        ),
    )
    op.create_index(
        "ix_discovery_terminal_outcomes_created_at",
        "discovery_terminal_outcomes",
        ["created_at"],
    )


def _upgrade_seed_profile() -> None:
    if not {"keyword_discovery_profiles", "keyword_discovery_profile_versions"} <= _tables():
        return
    bind = op.get_bind()
    profile = bind.execute(
        text("SELECT id, current_version FROM keyword_discovery_profiles WHERE name=:name"),
        {"name": "ecommerce-development-ru"},
    ).fetchone()
    if profile is None:
        return
    profile_id, current_version = int(profile[0]), int(profile[1])
    if current_version == 7:
        return
    if current_version != 6:
        raise RuntimeError(f"seed_profile_upgrade_requires_version_6:found={current_version}")
    exists = bind.execute(
        text(
            "SELECT id FROM keyword_discovery_profile_versions WHERE profile_id=:pid AND version=7"
        ),
        {"pid": profile_id},
    ).fetchone()
    if exists is None:
        bind.execute(
            text(
                "INSERT INTO keyword_discovery_profile_versions "
                "(profile_id,version,post_queries_json,directory_queries_json,"
                "replacement_directory_queries_json,required_service_profiles_json,"
                "additional_exclusions_json,"
                "source_scope,created_at) "
                "VALUES (:pid,7,:posts,:directories,:replacements,'[]',"
                ":exclusions,'all',CURRENT_TIMESTAMP)"
            ),
            {
                "pid": profile_id,
                "posts": json.dumps(POST_QUERIES, ensure_ascii=False),
                "directories": json.dumps(DIRECTORY_QUERIES, ensure_ascii=False),
                "replacements": json.dumps(REPLACEMENT_DIRECTORY_QUERIES, ensure_ascii=False),
                "exclusions": json.dumps(ADDITIONAL_EXCLUSIONS, ensure_ascii=False),
            },
        )
    bind.execute(
        text(
            "UPDATE keyword_discovery_profiles SET current_version=7, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:pid"
        ),
        {"pid": profile_id},
    )


def upgrade() -> None:
    _upgrade_profile_versions()
    _upgrade_runs()
    _upgrade_evidence()
    _upgrade_snapshots()
    _create_terminal_outcomes()
    _upgrade_seed_profile()


def downgrade() -> None:
    downgrade_seed_profile(op.get_bind(), _tables())
    if "discovery_terminal_outcomes" in _tables():
        op.drop_table("discovery_terminal_outcomes")
    snapshot_columns = (
        "qualification_reasons_json",
        "qualification_version",
        "sample_truncated",
        "latest_client_request_at",
        "unknown_author_message_count",
        "hard_excluded_count",
        "client_request_author_count",
        "client_request_count",
        "activity_distinct_author_count",
        "activity_active_day_count",
        "activity_message_count",
    )
    for name in snapshot_columns:
        if name in _columns("source_opportunity_snapshots"):
            op.drop_column("source_opportunity_snapshots", name)
    evidence_columns = _columns("source_discovery_evidence")
    if {"author_kind", "author_key"} & evidence_columns:
        checks = {
            item.get("name")
            for item in inspect(op.get_bind()).get_check_constraints("source_discovery_evidence")
        }
        with op.batch_alter_table("source_discovery_evidence", recreate="always") as batch:
            for constraint in (
                "ck_source_discovery_evidence_author_key",
                "ck_source_discovery_evidence_author_kind",
            ):
                if constraint in checks:
                    batch.drop_constraint(constraint, type_="check")
            for name in ("author_kind", "author_key"):
                if name in evidence_columns:
                    batch.drop_column(name)
    for name in (
        "run_termination_reason",
        "pool_exhausted_reason",
        "pool_exhausted",
        "gate_status",
        "reference_at",
    ):
        if name in _columns("discovery_runs"):
            op.drop_column("discovery_runs", name)
    if "replacement_directory_queries_json" in _columns("keyword_discovery_profile_versions"):
        op.drop_column(
            "keyword_discovery_profile_versions",
            "replacement_directory_queries_json",
        )
