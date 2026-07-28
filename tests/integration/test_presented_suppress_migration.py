"""Migration 005 presented-keyword suppress ledger (STO-020 / D-069).

Never mutates the live operator DB. Uses temp copies only.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command

from telegram_lead_discovery.storage.migrate import current_revision, make_alembic_config

HEAD_REVISION = "005_presented_keyword_suppress"
PREV_REVISION = "004_opportunity_truth_status"

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


def _downgrade_to(database_path: Path, revision: str) -> None:
    cfg = make_alembic_config(database_path)
    command.downgrade(cfg, revision)


def _stamp(database_path: Path, revision: str) -> None:
    cfg = make_alembic_config(database_path)
    command.stamp(cfg, revision)


def _connect(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(database_path)


def _table_names(database_path: Path) -> set[str]:
    conn = _connect(database_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _count(database_path: Path, sql: str, params: tuple = ()) -> int:
    conn = _connect(database_path)
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    finally:
        conn.close()


def test_migration_005_empty_db_creates_presented_ledger(tmp_path: Path) -> None:
    db = tmp_path / "rehearsal_005.sqlite3"
    _upgrade_to(db, HEAD_REVISION)
    assert current_revision(db) == HEAD_REVISION
    assert "presented_keyword_sources" in _table_names(db)


def test_migration_005_backfill_from_opportunity_snapshots(tmp_path: Path) -> None:
    db = tmp_path / "backfill_005.sqlite3"
    _upgrade_to(db, PREV_REVISION)
    # 001 create_all may already include current models; simulate pre-005 operator DB.
    conn = _connect(db)
    try:
        conn.execute("DROP TABLE IF EXISTS presented_keyword_sources")
        conn.commit()
    finally:
        conn.close()
    _stamp(db, PREV_REVISION)
    assert current_revision(db) == PREV_REVISION
    assert "presented_keyword_sources" not in _table_names(db)

    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()
    conn = _connect(db)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO discovery_runs (
                run_type, state, started_at, finished_at, created_at, version,
                counters_json, max_depth, expansion_cap, candidate_cap
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 2, 25, 100)
            """,
            ("keyword_scouting", "succeeded", now, now, now, 1),
        )
        run_a = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO discovery_runs (
                run_type, state, started_at, finished_at, created_at, version,
                counters_json, max_depth, expansion_cap, candidate_cap
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 2, 25, 100)
            """,
            ("keyword_scouting", "succeeded", now, now, now, 1),
        )
        run_b = int(cur.lastrowid)

        def _insert(run_id: int, tid: int, username: str) -> None:
            cur.execute(
                """
                INSERT INTO source_opportunity_snapshots (
                    run_id, source_telegram_id, username, title, source_type,
                    public_url, qualified_count, excluded_count, active_week_count,
                    ecommerce_qualified_count, sample_message_count, sample_timestamps,
                    score, band, score_components_json, discovery_channels_json,
                    review_state, version, created_at, updated_at, truth_status,
                    verification_scanned_count
                ) VALUES (
                    ?, ?, ?, ?, 'megagroup',
                    ?, 1, 0, 1,
                    0, 1, '[]',
                    10, 'weak', '{}', '["directory"]',
                    'unreviewed', 1, ?, ?, 'rejected', 10
                )
                """,
                (
                    run_id,
                    tid,
                    username,
                    username,
                    f"https://t.me/{username}",
                    now,
                    now,
                ),
            )

        _insert(run_a, 701, "alpha_chat")
        _insert(run_a, 702, "beta_chat")
        _insert(run_b, 701, "alpha_chat")  # same peer, second run → one ledger row
        conn.commit()
    finally:
        conn.close()

    _upgrade_to(db, HEAD_REVISION)
    assert current_revision(db) == HEAD_REVISION
    assert "presented_keyword_sources" in _table_names(db)
    # Duplicate telegram_id 701 backfills once (idempotent unique).
    assert _count(db, "SELECT COUNT(*) FROM presented_keyword_sources") == 2
    assert (
        _count(
            db,
            "SELECT COUNT(*) FROM presented_keyword_sources WHERE source_telegram_id = 701",
        )
        == 1
    )

    # Re-upgrade is idempotent.
    _upgrade_to(db, HEAD_REVISION)
    assert _count(db, "SELECT COUNT(*) FROM presented_keyword_sources") == 2

    _downgrade_to(db, PREV_REVISION)
    assert current_revision(db) == PREV_REVISION
    assert "presented_keyword_sources" not in _table_names(db)


def test_operator_db_copy_rehearsal_to_005(tmp_path: Path) -> None:
    """Copy live operator DB → temp, upgrade to 005; live untouched."""
    if not OPERATOR_DB.is_file():
        pytest.skip("operator DB not present")

    live_before = current_revision(OPERATOR_DB)
    copy_path = tmp_path / "operator_copy_app_005.sqlite3"
    src = sqlite3.connect(f"file:{OPERATOR_DB}?mode=ro", uri=True)
    try:
        live_opp = src.execute(
            "SELECT COUNT(*) FROM source_opportunity_snapshots"
        ).fetchone()[0]
        dst = sqlite3.connect(copy_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    assert current_revision(copy_path) == live_before
    _upgrade_to(copy_path, HEAD_REVISION)
    assert current_revision(copy_path) == HEAD_REVISION

    conn = sqlite3.connect(copy_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok"
        assert "presented_keyword_sources" in {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        presented_n = conn.execute(
            "SELECT COUNT(*) FROM presented_keyword_sources"
        ).fetchone()[0]
        # Every historical opportunity peer yields ≥1 ledger row (may be fewer than
        # snapshots if duplicate telegram ids collapsed).
        assert presented_n >= 1 or live_opp == 0
        if live_opp > 0:
            assert presented_n >= 1
            distinct_peers = conn.execute(
                "SELECT COUNT(DISTINCT source_telegram_id) "
                "FROM source_opportunity_snapshots "
                "WHERE source_telegram_id IS NOT NULL"
            ).fetchone()[0]
            assert presented_n >= distinct_peers or presented_n == distinct_peers
    finally:
        conn.close()

    assert current_revision(OPERATOR_DB) == live_before
