"""Migration 006 ActiveClientChat v1 rehearsal; live DB is read-only."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from telegram_lead_discovery.storage.migrate import current_revision, make_alembic_config

HEAD_REVISION = "006_active_client_chat_v1"
PREV_REVISION = "005_presented_keyword_suppress"
OPERATOR_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "TelegramLeadDiscovery/data/app.sqlite3"


def _upgrade_to(path: Path, revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(make_alembic_config(path), revision)


def _downgrade_to(path: Path, revision: str) -> None:
    command.downgrade(make_alembic_config(path), revision)


def _copy_readonly(source_path: Path, target_path: Path) -> None:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def test_operator_copy_upgrades_to_006_without_touching_live(tmp_path: Path) -> None:
    if not OPERATOR_DB.is_file():
        pytest.skip("operator DB not present")
    live_before = current_revision(OPERATOR_DB)
    if live_before != PREV_REVISION:
        pytest.skip(f"operator DB is not at {PREV_REVISION}: {live_before}")

    copy_path = tmp_path / "operator-copy.sqlite3"
    _copy_readonly(OPERATOR_DB, copy_path)
    _upgrade_to(copy_path, HEAD_REVISION)

    assert current_revision(OPERATOR_DB) == live_before
    assert current_revision(copy_path) == HEAD_REVISION
    connection = sqlite3.connect(copy_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        current = connection.execute(
            "SELECT current_version FROM keyword_discovery_profiles WHERE name=?",
            ("ecommerce-development-ru",),
        ).fetchone()
        assert current == (7,)
        assert "reference_at" in _columns(connection, "discovery_runs")
        assert "author_kind" in _columns(connection, "source_discovery_evidence")
        assert "qualification_version" in _columns(connection, "source_opportunity_snapshots")
        assert "replacement_directory_queries_json" in _columns(
            connection, "keyword_discovery_profile_versions"
        )
        replacements = connection.execute(
            "SELECT replacement_directory_queries_json "
            "FROM keyword_discovery_profile_versions WHERE version=7"
        ).fetchone()
        assert replacements is not None and len(json.loads(replacements[0])) == 15
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' "
            "AND name='discovery_terminal_outcomes'"
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_migration_006_rejects_unapproved_seed_version(tmp_path: Path) -> None:
    database = tmp_path / "wrong-seed.sqlite3"
    _upgrade_to(database, PREV_REVISION)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO keyword_discovery_profiles "
            "(name,state,current_version,created_at,updated_at) "
            "VALUES ('ecommerce-development-ru','active',5,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="requires_version_6:found=5"):
        _upgrade_to(database, HEAD_REVISION)


def test_migration_006_schema_constraints(tmp_path: Path) -> None:
    database = tmp_path / "schema.sqlite3"
    _upgrade_to(database, HEAD_REVISION)
    connection = sqlite3.connect(database)
    try:
        evidence_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='source_discovery_evidence'"
        ).fetchone()[0]
        outcome_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='discovery_terminal_outcomes'"
        ).fetchone()[0]
        assert "ck_source_discovery_evidence_author_key" in evidence_sql
        assert "ck_source_discovery_evidence_author_kind" in evidence_sql
        assert "uq_discovery_terminal_outcome_version" in outcome_sql
        assert "ck_discovery_terminal_outcome_truth" in outcome_sql
        assert "ck_discovery_terminal_outcome_stop_reason" in outcome_sql
    finally:
        connection.close()


def test_migration_006_downgrade_restores_seed_version_6(tmp_path: Path) -> None:
    database = tmp_path / "rollback.sqlite3"
    _upgrade_to(database, PREV_REVISION)
    connection = sqlite3.connect(database)
    try:
        cursor = connection.execute(
            "INSERT INTO keyword_discovery_profiles "
            "(name,state,current_version,created_at,updated_at) "
            "VALUES ('ecommerce-development-ru','active',6,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO keyword_discovery_profile_versions "
            "(profile_id,version,post_queries_json,directory_queries_json,"
            "replacement_directory_queries_json,required_service_profiles_json,"
            "additional_exclusions_json,source_scope,created_at) "
            "VALUES (?,6,'[\"old query\"]','[]','[]','[]','[]',"
            "'all',CURRENT_TIMESTAMP)",
            (cursor.lastrowid,),
        )
        connection.commit()
    finally:
        connection.close()

    _upgrade_to(database, HEAD_REVISION)
    _downgrade_to(database, PREV_REVISION)

    connection = sqlite3.connect(database)
    try:
        assert current_revision(database) == PREV_REVISION
        assert "replacement_directory_queries_json" not in _columns(
            connection, "keyword_discovery_profile_versions"
        )
        assert connection.execute(
            "SELECT current_version FROM keyword_discovery_profiles WHERE name=?",
            ("ecommerce-development-ru",),
        ).fetchone() == (6,)
        assert connection.execute(
            "SELECT count(*) FROM keyword_discovery_profile_versions WHERE version=7"
        ).fetchone() == (0,)
    finally:
        connection.close()
