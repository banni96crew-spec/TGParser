"""Online SQLite backup and restore (INF-011..INF-016)."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.infrastructure.paths import AppPaths, ensure_app_directories
from telegram_lead_discovery.storage.models import BackupManifest


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row and row[0] == "ok")
    finally:
        conn.close()


async def create_online_backup(
    session: AsyncSession,
    *,
    paths: AppPaths | None = None,
    backup_type: str = "daily",
) -> BackupManifest:
    resolved = ensure_app_directories(paths)
    source = resolved.database_path
    if not source.exists():
        raise FileNotFoundError(str(source))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    tmp = resolved.tmp_dir / f"backup-{stamp}.sqlite3.tmp"
    final = resolved.backups_dir / f"{backup_type}-{stamp}.sqlite3"
    suffix = 0
    while final.exists():
        suffix += 1
        final = resolved.backups_dir / f"{backup_type}-{stamp}-{suffix}.sqlite3"
    # Prefer SQLite backup API for online-safe copy.
    src = sqlite3.connect(source)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    if not _integrity_ok(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("backup_integrity_failed")
    tmp.replace(final)
    manifest = BackupManifest(
        path_ref=str(final),
        backup_type=backup_type,
        database_checksum=_checksum(final),
        database_size=final.stat().st_size,
        schema_version="001_initial",
        integrity_result="ok",
        verified_at=datetime.now(UTC),
    )
    session.add(manifest)
    await session.flush()
    return manifest


def restore_backup(
    *,
    backup_path: Path,
    paths: AppPaths | None = None,
    runtime_running: bool = False,
) -> Path:
    if runtime_running:
        raise RuntimeError("restore_requires_stopped_runtime")
    resolved = ensure_app_directories(paths)
    if not backup_path.is_file():
        raise FileNotFoundError(str(backup_path))
    if resolved.backups_dir.resolve() not in backup_path.resolve().parents:
        raise ValueError("backup_outside_backups_dir")
    if not _integrity_ok(backup_path):
        raise RuntimeError("corrupt_backup")
    active = resolved.database_path
    rollback = resolved.tmp_dir / f"rollback-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    if active.exists():
        shutil.copy2(active, rollback)
    shutil.copy2(backup_path, active)
    if not _integrity_ok(active):
        if rollback.exists():
            shutil.copy2(rollback, active)
        raise RuntimeError("post_restore_integrity_failed")
    return active


def rotate_backups(
    paths: AppPaths | None = None,
    *,
    keep_daily: int = 7,
    keep_weekly: int = 4,
) -> int:
    """Keep the newest ``keep_daily`` daily and ``keep_weekly`` weekly backup files."""
    resolved = ensure_app_directories(paths)
    removed = 0
    dailies = sorted(resolved.backups_dir.glob("daily-*.sqlite3"), reverse=True)
    for stale in dailies[keep_daily:]:
        stale.unlink(missing_ok=True)
        removed += 1
    weeklies = sorted(resolved.backups_dir.glob("weekly-*.sqlite3"), reverse=True)
    for stale in weeklies[keep_weekly:]:
        stale.unlink(missing_ok=True)
        removed += 1
    return removed
