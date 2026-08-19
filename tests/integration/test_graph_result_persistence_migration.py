from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from telegram_lead_discovery.storage.migrate import current_revision, make_alembic_config

PREVIOUS = "007_graph_request_control"
CURRENT = "008_graph_result_persistence"


def _upgrade(path: Path, revision: str) -> None:
    command.upgrade(make_alembic_config(path), revision)


def test_graph_result_table_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "graph-results.sqlite3"
    _upgrade(database, PREVIOUS)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS graph_discovery_posts")
        connection.commit()

    _upgrade(database, CURRENT)
    assert current_revision(database) == CURRENT
    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(graph_discovery_posts)")
        }
        assert {
            "run_id",
            "source_id",
            "parent_source_id",
            "source_telegram_id",
            "source_username",
            "source_url",
            "request_ordinal",
            "telegram_message_id",
            "published_at",
            "message_text",
            "author_key",
            "author_kind",
            "permalink",
        } <= columns
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok"

    command.downgrade(make_alembic_config(database), PREVIOUS)
    assert current_revision(database) == PREVIOUS
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='graph_discovery_posts'"
        ).fetchone()
        assert row is None
