from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from telegram_lead_discovery.storage.migrate import (
    current_revision,
    make_alembic_config,
)

PREVIOUS = "006_active_client_chat_v1"
CURRENT = "007_graph_request_control"


def _upgrade(path: Path, revision: str) -> None:
    command.upgrade(make_alembic_config(path), revision)


def _downgrade(path: Path, revision: str) -> None:
    command.downgrade(make_alembic_config(path), revision)


def _columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _index_exists(path: Path) -> bool:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='uq_discovery_runs_one_active_telegram'"
        ).fetchone()
    return row is not None


def _simulate_pre_007_schema(path: Path) -> None:
    # Migration 001 historically calls current metadata; remove the new column
    # so this test exercises the real 006 -> 007 transition.
    with sqlite3.connect(path) as connection:
        if "access_hash" in _columns(path, "telegram_sources"):
            connection.execute("ALTER TABLE telegram_sources DROP COLUMN access_hash")
        connection.commit()


def test_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite3"
    _upgrade(database, PREVIOUS)
    _simulate_pre_007_schema(database)
    assert "access_hash" not in _columns(database, "telegram_sources")
    assert not _index_exists(database)

    _upgrade(database, CURRENT)
    assert current_revision(database) == CURRENT
    assert "access_hash" in _columns(database, "telegram_sources")
    assert _index_exists(database)

    _downgrade(database, PREVIOUS)
    assert current_revision(database) == PREVIOUS
    assert "access_hash" not in _columns(database, "telegram_sources")
    assert not _index_exists(database)


def test_migration_conflict_preflight_applies_no_ddl(tmp_path: Path) -> None:
    database = tmp_path / "conflict.sqlite3"
    _upgrade(database, PREVIOUS)
    _simulate_pre_007_schema(database)
    with sqlite3.connect(database) as connection:
        for run_type in ("graph", "keyword_scouting"):
            connection.execute(
                "INSERT INTO discovery_runs "
                "(run_type,max_depth,expansion_cap,candidate_cap,state,version,"
                "counters_json,gate_status,pool_exhausted,created_at) "
                "VALUES (?,2,25,100,'running',1,'{}','inconclusive',0,CURRENT_TIMESTAMP)",
                (run_type,),
            )
        connection.commit()

    with pytest.raises(
        RuntimeError,
        match=r"active_telegram_discovery_conflict:1,2",
    ):
        _upgrade(database, CURRENT)

    assert current_revision(database) == PREVIOUS
    assert "access_hash" not in _columns(database, "telegram_sources")
    assert not _index_exists(database)
