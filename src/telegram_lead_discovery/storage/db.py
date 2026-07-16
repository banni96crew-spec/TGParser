from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from telegram_lead_discovery.storage.models import Base

_ENGINE: AsyncEngine | None = None
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None


def _apply_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


async def init_engine(path: Path) -> AsyncEngine:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
    engine = create_async_engine(get_database_url(path), future=True)
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    _ENGINE = engine
    _SESSION_FACTORY = async_sessionmaker(engine, expire_on_commit=False)
    return engine


async def dispose_engine() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def get_engine() -> AsyncEngine:
    if _ENGINE is None:
        raise RuntimeError("database engine is not initialized")
    return _ENGINE


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _SESSION_FACTORY is None:
        raise RuntimeError("database session factory is not initialized")
    return _SESSION_FACTORY


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def integrity_check_ok() -> bool:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA integrity_check"))
        row = result.first()
        return bool(row and row[0] == "ok")


async def pragma_probe() -> dict[str, str]:
    engine = get_engine()
    async with engine.connect() as conn:
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
        busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
    return {
        "foreign_keys": int(fk),
        "journal_mode": str(journal).upper(),
        "busy_timeout": int(busy),
    }


async def probe_pragmas(engine: AsyncEngine | None = None) -> dict[str, object]:
    eng = engine or get_engine()
    async with eng.connect() as conn:
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
        busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
    return {
        "foreign_keys": int(fk),
        "journal_mode": str(journal).upper(),
        "busy_timeout": int(busy),
    }
