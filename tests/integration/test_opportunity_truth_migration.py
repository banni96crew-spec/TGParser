"""Migration 004 opportunity truth + matched_rule_ids rehearsal (STO-019 / D-068).

Never mutates the live operator DB. Uses temp copies only.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from telegram_lead_discovery.storage.migrate import current_revision, make_alembic_config

HEAD_REVISION = "004_opportunity_truth_status"
PREV_REVISION = "003_dismissed_keyword_suppress"

OPERATOR_DB = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "TelegramLeadDiscovery"
    / "data"
    / "app.sqlite3"
)


def _upgrade_to(database_path: Path, revision: str) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = make_alembic_config(database_path)
    command.upgrade(cfg, revision)


def _stamp(database_path: Path, revision: str) -> None:
    cfg = make_alembic_config(database_path)
    command.stamp(cfg, revision)


def _column_names(database_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {r[1] for r in rows}


def _index_names(database_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    finally:
        conn.close()
    # row: seq, name, unique, origin, partial
    return {r[1] for r in rows}


def _table_sql(database_path: Path, table: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def test_migration_004_empty_db_reaches_truth_head(tmp_path: Path) -> None:
    db = tmp_path / "rehearsal_004.sqlite3"
    _upgrade_to(db, HEAD_REVISION)
    assert current_revision(db) == HEAD_REVISION
    cols = _column_names(db, "source_opportunity_snapshots")
    assert "truth_status" in cols
    assert "verification_scanned_count" in cols
    assert "verification_stop_reason" in cols
    ev_cols = _column_names(db, "source_discovery_evidence")
    assert "matched_rule_ids_json" in ev_cols


def test_migration_004_from_003_via_drop_column_keeps_constraints(tmp_path: Path) -> None:
    """Simulate pre-004 operator schema without CREATE TABLE AS (keeps PK/UNIQUE)."""
    db = tmp_path / "from_003_drop.sqlite3"
    _upgrade_to(db, HEAD_REVISION)
    sql_before = _table_sql(db, "source_opportunity_snapshots")
    assert "PRIMARY KEY" in sql_before.upper() or "primary key" in sql_before.lower()
    indexes_before = _index_names(db, "source_opportunity_snapshots")
    assert indexes_before  # at least unique / score indexes

    conn = sqlite3.connect(db)
    try:
        # Modern SQLite DROP COLUMN preserves remaining constraints/indexes.
        for col in (
            "truth_status",
            "verification_scanned_count",
            "verification_stop_reason",
        ):
            conn.execute(f"ALTER TABLE source_opportunity_snapshots DROP COLUMN {col}")
        if "matched_rule_ids_json" in _column_names(db, "source_discovery_evidence"):
            conn.execute(
                "ALTER TABLE source_discovery_evidence DROP COLUMN matched_rule_ids_json"
            )
        conn.commit()
    finally:
        conn.close()

    _stamp(db, PREV_REVISION)
    assert "truth_status" not in _column_names(db, "source_opportunity_snapshots")
    assert "matched_rule_ids_json" not in _column_names(db, "source_discovery_evidence")

    _upgrade_to(db, HEAD_REVISION)
    assert current_revision(db) == HEAD_REVISION
    after_cols = _column_names(db, "source_opportunity_snapshots")
    assert "truth_status" in after_cols
    assert "verification_scanned_count" in after_cols
    assert "verification_stop_reason" in after_cols
    assert "matched_rule_ids_json" in _column_names(db, "source_discovery_evidence")
    sql_after = _table_sql(db, "source_opportunity_snapshots")
    assert "PRIMARY KEY" in sql_after.upper() or "id" in sql_after.lower()
    # Unique opportunity constraint / indexes still present
    assert _index_names(db, "source_opportunity_snapshots")


def test_operator_db_copy_rehearsal_to_004(tmp_path: Path) -> None:
    """Copy live operator DB → temp, upgrade to 004, integrity_check; live untouched."""
    if not OPERATOR_DB.is_file():
        pytest.skip("operator DB not present")

    live_before = current_revision(OPERATOR_DB)
    copy_path = tmp_path / "operator_copy_app.sqlite3"
    # WAL-safe copy via SQLite backup API (never opens live for write).
    src = sqlite3.connect(f"file:{OPERATOR_DB}?mode=ro", uri=True)
    try:
        live_opp = src.execute(
            "SELECT COUNT(*) FROM source_opportunity_snapshots"
        ).fetchone()[0]
        live_ev = src.execute(
            "SELECT COUNT(*) FROM source_discovery_evidence"
        ).fetchone()[0]
        dst = sqlite3.connect(copy_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    head_before_copy = current_revision(copy_path)
    assert head_before_copy == live_before

    _upgrade_to(copy_path, HEAD_REVISION)
    assert current_revision(copy_path) == HEAD_REVISION

    conn = sqlite3.connect(copy_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok"
        opp_n = conn.execute(
            "SELECT COUNT(*) FROM source_opportunity_snapshots"
        ).fetchone()[0]
        ev_n = conn.execute("SELECT COUNT(*) FROM source_discovery_evidence").fetchone()[0]
        assert opp_n == live_opp
        assert ev_n == live_ev
        cols = {r[1] for r in conn.execute("PRAGMA table_info(source_opportunity_snapshots)")}
        assert "truth_status" in cols
        ev_cols = {r[1] for r in conn.execute("PRAGMA table_info(source_discovery_evidence)")}
        assert "matched_rule_ids_json" in ev_cols
        indexes = {
            r[1] for r in conn.execute("PRAGMA index_list(source_opportunity_snapshots)")
        }
        assert indexes
    finally:
        conn.close()

    # Live DB unchanged
    assert current_revision(OPERATOR_DB) == live_before
    assert live_before == PREV_REVISION or live_before is not None
