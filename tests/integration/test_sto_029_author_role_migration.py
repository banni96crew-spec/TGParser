"""AT-STO-029: v7 role-result columns upgrade and downgrade safely."""

import sqlite3
from pathlib import Path

from alembic import command

from telegram_lead_discovery.storage.migrate import make_alembic_config


PREVIOUS = "013_account_request_gate"


def _columns(database: Path, table: str) -> dict[str, tuple]:
    with sqlite3.connect(database) as connection:
        return {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}


def test_at_sto_029_role_result_columns_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "app.sqlite3"
    config = make_alembic_config(database)
    command.upgrade(config, PREVIOUS)

    # The initial migration builds from current metadata in this repository,
    # so simulate a genuine pre-014 operator schema explicitly.
    with sqlite3.connect(database) as connection:
        for table in ("processing_results", "history_scan_results"):
            connection.execute(f"ALTER TABLE {table} DROP COLUMN author_role")
            connection.execute(f"ALTER TABLE {table} DROP COLUMN author_role_rule_ids_json")
        connection.commit()

    command.upgrade(config, "014_detection_author_role")
    for table in ("processing_results", "history_scan_results"):
        columns = _columns(database, table)
        assert columns["author_role"][3] == 1
        assert columns["author_role"][4] == "'legacy'"
        assert columns["author_role_rule_ids_json"][3] == 1
        assert columns["author_role_rule_ids_json"][4] == "'[]'"

    command.downgrade(config, PREVIOUS)
    for table in ("processing_results", "history_scan_results"):
        assert "author_role" not in _columns(database, table)
        assert "author_role_rule_ids_json" not in _columns(database, table)
