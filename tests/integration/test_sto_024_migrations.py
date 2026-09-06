"""AT-STO-024: suppress_class 009 then profile v8 010. Temp DB only."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command

from telegram_lead_discovery.storage.alembic_data.active_client_chat_v1_profile import (
    ADDITIONAL_EXCLUSIONS,
    DIRECTORY_QUERIES,
    POST_QUERIES,
    REPLACEMENT_DIRECTORY_QUERIES,
)
from telegram_lead_discovery.storage.migrate import current_revision, make_alembic_config

PREVIOUS = "008_graph_result_persistence"
MID = "009_presented_suppress_class"
HEAD = "010_keyword_profile_v8"
LEGACY_COUNT = 138


def _upgrade(path: Path, revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(make_alembic_config(path), revision)


def _downgrade(path: Path, revision: str) -> None:
    command.downgrade(make_alembic_config(path), revision)


def _columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _insert_v7_profile(connection: sqlite3.Connection) -> None:
    cursor = connection.execute(
        "INSERT INTO keyword_discovery_profiles "
        "(name,state,current_version,created_at,updated_at) "
        "VALUES ('ecommerce-development-ru','active',7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
    )
    connection.execute(
        "INSERT INTO keyword_discovery_profile_versions "
        "(profile_id,version,post_queries_json,directory_queries_json,"
        "replacement_directory_queries_json,required_service_profiles_json,"
        "additional_exclusions_json,source_scope,created_at) "
        "VALUES (?,7,?,?,?,'[]',?,'all',CURRENT_TIMESTAMP)",
        (
            cursor.lastrowid,
            json.dumps(list(POST_QUERIES), ensure_ascii=False),
            json.dumps(list(DIRECTORY_QUERIES), ensure_ascii=False),
            json.dumps(list(REPLACEMENT_DIRECTORY_QUERIES), ensure_ascii=False),
            json.dumps(list(ADDITIONAL_EXCLUSIONS), ensure_ascii=False),
        ),
    )


def test_009_backfill_quality_and_legacy(tmp_path: Path) -> None:
    database = tmp_path / "suppress-class.sqlite3"
    _upgrade(database, PREVIOUS)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO discovery_runs "
            "(run_type,max_depth,expansion_cap,candidate_cap,state,version,"
            "counters_json,gate_status,pool_exhausted,created_at) "
            "VALUES ('keyword_scouting',2,25,100,'succeeded',1,'{}','fail',0,?)",
            (now,),
        )
        run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        rows = [
            (f"peer:{tid}", tid, f"u{tid}", "[]", now, 1, now, now)
            for tid in range(1, LEGACY_COUNT + 1)
        ]
        connection.executemany(
            "INSERT INTO presented_keyword_sources "
            "(canonical_key,source_telegram_id,username_normalized,aliases_json,"
            "first_presented_at,version,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.execute(
            """
            INSERT INTO source_opportunity_snapshots (
                run_id, source_telegram_id, username, title, source_type,
                public_url, qualified_count, excluded_count, active_week_count,
                ecommerce_qualified_count, sample_message_count, sample_timestamps,
                score, band, score_components_json, discovery_channels_json,
                review_state, version, created_at, updated_at, truth_status,
                verification_scanned_count
            ) VALUES (
                ?, 1, 'u1', 'u1', 'megagroup',
                'https://t.me/u1', 1, 0, 1,
                0, 1, '[]',
                80, 'promising', '{}', '["global_message"]',
                'unreviewed', 1, ?, ?, 'quality', 100
            )
            """,
            (run_id, now, now),
        )
        connection.commit()

    _upgrade(database, MID)
    assert current_revision(database) == MID
    assert "suppress_class" in _columns(database, "presented_keyword_sources")
    with sqlite3.connect(database) as connection:
        quality = connection.execute(
            "SELECT COUNT(*) FROM presented_keyword_sources "
            "WHERE suppress_class='quality'"
        ).fetchone()[0]
        legacy = connection.execute(
            "SELECT COUNT(*) FROM presented_keyword_sources "
            "WHERE suppress_class='legacy_unspecified'"
        ).fetchone()[0]
        assert quality == 1
        assert legacy == LEGACY_COUNT - 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    _downgrade(database, PREVIOUS)
    assert current_revision(database) == PREVIOUS
    assert "suppress_class" not in _columns(database, "presented_keyword_sources")


def test_010_upgrades_v7_and_blocks_wrong_version(tmp_path: Path) -> None:
    database = tmp_path / "profile-v8.sqlite3"
    _upgrade(database, MID)
    with sqlite3.connect(database) as connection:
        _insert_v7_profile(connection)
        connection.commit()

    _upgrade(database, HEAD)
    assert current_revision(database) == HEAD
    with sqlite3.connect(database) as connection:
        current = connection.execute(
            "SELECT current_version FROM keyword_discovery_profiles "
            "WHERE name='ecommerce-development-ru'"
        ).fetchone()
        assert current == (8,)
        row = connection.execute(
            "SELECT post_queries_json, directory_queries_json, "
            "replacement_directory_queries_json, additional_exclusions_json, "
            "source_scope FROM keyword_discovery_profile_versions WHERE version=8"
        ).fetchone()
        assert json.loads(row[0]) == list(POST_QUERIES)
        assert json.loads(row[1]) == []
        assert json.loads(row[2]) == []
        assert json.loads(row[3]) == list(ADDITIONAL_EXCLUSIONS)
        assert row[4] == "groups"
        v7 = connection.execute(
            "SELECT COUNT(*) FROM keyword_discovery_profile_versions WHERE version=7"
        ).fetchone()[0]
        assert v7 == 1

    _downgrade(database, MID)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT current_version FROM keyword_discovery_profiles "
            "WHERE name='ecommerce-development-ru'"
        ).fetchone() == (7,)
        assert connection.execute(
            "SELECT COUNT(*) FROM keyword_discovery_profile_versions WHERE version=8"
        ).fetchone() == (1,)

    blocked = tmp_path / "wrong-version.sqlite3"
    _upgrade(blocked, MID)
    with sqlite3.connect(blocked) as connection:
        connection.execute(
            "INSERT INTO keyword_discovery_profiles "
            "(name,state,current_version,created_at,updated_at) "
            "VALUES ('ecommerce-development-ru','active',3,CURRENT_TIMESTAMP,"
            "CURRENT_TIMESTAMP)"
        )
        connection.commit()
    with pytest.raises(Exception, match="requires_version_7:found=3"):
        _upgrade(blocked, HEAD)


def test_010_downgrade_blocked_while_keyword_run_active(tmp_path: Path) -> None:
    database = tmp_path / "active-run.sqlite3"
    _upgrade(database, MID)
    with sqlite3.connect(database) as connection:
        _insert_v7_profile(connection)
        connection.commit()
    _upgrade(database, HEAD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO discovery_runs "
            "(run_type,max_depth,expansion_cap,candidate_cap,state,version,"
            "counters_json,gate_status,pool_exhausted,created_at) "
            "VALUES ('keyword_scouting',2,25,100,'running',1,'{}','inconclusive',"
            "0,CURRENT_TIMESTAMP)"
        )
        connection.commit()
    with pytest.raises(Exception, match="downgrade_blocked_active_keyword_run"):
        _downgrade(database, MID)
    assert current_revision(database) == HEAD
