"""Integration — Wave 02 migration 003 dismiss suppress ledger (STO-017 / AT-STO-017).

Covers: empty DB → head, populated 002 → historical backfill, re-migrate idempotent.
Uses temp SQLite only (no live DB).

Note: revision 001 uses Base.metadata.create_all (current models). A true pre-003
operator DB is simulated by stamping 002 and dropping the suppress table before
upgrade to head.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command

from telegram_lead_discovery.storage.migrate import (
    current_revision,
    make_alembic_config,
    upgrade_head,
)

HEAD_REVISION = "006_active_client_chat_v1"
PREV_REVISION = "002_keyword_source_discovery"


def _upgrade_to(database_path: Path, revision: str) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = make_alembic_config(database_path)
    command.upgrade(cfg, revision)


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


def _column_names(database_path: Path, table: str) -> set[str]:
    conn = _connect(database_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _prepare_populated_002_db(database_path: Path) -> None:
    """Build schema through 002, drop suppress ledger, stamp 002, seed dismissed snaps."""
    _upgrade_to(database_path, PREV_REVISION)
    conn = _connect(database_path)
    try:
        conn.execute("DROP TABLE IF EXISTS dismissed_keyword_sources")
        conn.commit()
    finally:
        conn.close()
    _stamp(database_path, PREV_REVISION)
    assert current_revision(database_path) == PREV_REVISION
    assert "dismissed_keyword_sources" not in _table_names(database_path)
    _seed_dismissed_snapshots(database_path)


def _seed_dismissed_snapshots(database_path: Path) -> dict[str, int]:
    """Seed historical dismissed opportunities without any suppress ledger rows."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()
    conn = _connect(database_path)
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
        run_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO discovery_runs (
                run_type, state, started_at, finished_at, created_at, version,
                counters_json, max_depth, expansion_cap, candidate_cap
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 2, 25, 100)
            """,
            ("keyword_scouting", "succeeded", now, now, now, 1),
        )
        run_id_b = int(cur.lastrowid)

        def _insert(
            *,
            run: int,
            telegram_id: int,
            username: str,
            title: str,
            source_type: str,
            review_state: str,
            dismiss_reason: str | None,
        ) -> int:
            cur.execute(
                """
                INSERT INTO source_opportunity_snapshots (
                    run_id, source_telegram_id, username, title, source_type,
                    public_url, qualified_count, excluded_count, active_week_count,
                    ecommerce_qualified_count, sample_message_count, sample_timestamps,
                    score, band, truth_status, verification_scanned_count,
                    score_components_json, discovery_channels_json,
                    review_state, dismiss_reason, version, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, 0, 0, 0,
                    0, 0, '[]',
                    10, 'weak', 'inconclusive', 0, '{}', '["global_message"]',
                    ?, ?, 1, ?, ?
                )
                """,
                (
                    run,
                    telegram_id,
                    username,
                    title,
                    source_type,
                    f"https://t.me/{username}",
                    review_state,
                    dismiss_reason,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

        opp_old = _insert(
            run=run_id,
            telegram_id=500_001,
            username="old_shop",
            title="Old Shop",
            source_type="channel",
            review_state="dismissed",
            dismiss_reason="noise",
        )
        opp_new = _insert(
            run=run_id_b,
            telegram_id=500_001,
            username="new_shop",
            title="New Shop",
            source_type="channel",
            review_state="dismissed",
            dismiss_reason="noise",
        )
        opp_other = _insert(
            run=run_id,
            telegram_id=500_002,
            username="other_chat",
            title="Other",
            source_type="megagroup",
            review_state="dismissed",
            dismiss_reason="spam",
        )
        _insert(
            run=run_id,
            telegram_id=500_003,
            username="kept",
            title="Kept",
            source_type="channel",
            review_state="unreviewed",
            dismiss_reason=None,
        )
        conn.commit()
        return {
            "run_a": run_id,
            "run_b": run_id_b,
            "opp_old": opp_old,
            "opp_new": opp_new,
            "opp_other": opp_other,
        }
    finally:
        conn.close()


def test_migration_empty_db_reaches_suppress_head(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    upgrade_head(db_path)
    assert current_revision(db_path) == HEAD_REVISION
    assert "dismissed_keyword_sources" in _table_names(db_path)
    assert _count(db_path, "SELECT COUNT(*) FROM dismissed_keyword_sources") == 0


def test_migration_populated_002_backfills_historical_dismiss(tmp_path: Path) -> None:
    """AT-STO-017: every historical dismissed identity yields ≥1 suppress membership."""
    db_path = tmp_path / "from002.sqlite3"
    _prepare_populated_002_db(db_path)

    dismissed_before = _count(
        db_path,
        "SELECT COUNT(*) FROM source_opportunity_snapshots WHERE review_state = 'dismissed'",
    )
    assert dismissed_before == 3

    upgrade_head(db_path)
    assert current_revision(db_path) == HEAD_REVISION
    assert "dismissed_keyword_sources" in _table_names(db_path)

    suppress_count = _count(db_path, "SELECT COUNT(*) FROM dismissed_keyword_sources")
    # Rename collision for peer 500_001 → one suppress; plus peer 500_002 → one.
    assert suppress_count == 2

    peer_rows = _count(
        db_path,
        "SELECT COUNT(*) FROM dismissed_keyword_sources WHERE source_telegram_id = ?",
        (500_001,),
    )
    assert peer_rows == 1

    cols = _column_names(db_path, "dismissed_keyword_sources")
    assert "canonical_key" in cols

    conn = _connect(db_path)
    try:
        keys = {
            r[0]
            for r in conn.execute(
                "SELECT canonical_key FROM dismissed_keyword_sources"
            ).fetchall()
        }
    finally:
        conn.close()
    assert keys == {"peer:500001", "peer:500002"}


def test_migration_remigrate_idempotent_counts_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent.sqlite3"
    _prepare_populated_002_db(db_path)
    upgrade_head(db_path)
    first = _count(db_path, "SELECT COUNT(*) FROM dismissed_keyword_sources")
    assert first == 2

    upgrade_head(db_path)
    second = _count(db_path, "SELECT COUNT(*) FROM dismissed_keyword_sources")
    assert second == first
    assert current_revision(db_path) == HEAD_REVISION
