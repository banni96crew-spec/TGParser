"""Run Alembic migrations programmatically (sync — INF-018)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

PACKAGE_DIR = Path(__file__).resolve().parent
ALEMBIC_INI = PACKAGE_DIR / "alembic.ini"


def make_alembic_config(database_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PACKAGE_DIR / "alembic"))
    # Sync URL — env.py converts aiosqlite if needed; prefer sync here.
    url = f"sqlite:///{database_path.resolve().as_posix()}"
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade_head(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = make_alembic_config(database_path)
    command.upgrade(cfg, "head")


def current_revision(database_path: Path) -> str | None:
    sync_url = f"sqlite:///{database_path.resolve().as_posix()}"
    engine = create_engine(sync_url)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        return context.get_current_revision()
