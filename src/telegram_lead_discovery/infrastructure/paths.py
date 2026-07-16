from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from telegram_lead_discovery.security.session_paths import app_root


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    data_dir: Path
    secrets_dir: Path
    logs_dir: Path
    backups_dir: Path
    exports_dir: Path
    tmp_dir: Path
    database_path: Path
    process_lock_path: Path


def resolve_app_paths() -> AppPaths:
    root = app_root()
    data_dir = root / "data"
    return AppPaths(
        root=root,
        data_dir=data_dir,
        secrets_dir=root / "secrets",
        logs_dir=root / "logs",
        backups_dir=root / "backups",
        exports_dir=root / "exports",
        tmp_dir=root / "tmp",
        database_path=data_dir / "app.sqlite3",
        process_lock_path=data_dir / "app.lock",
    )


def ensure_app_directories(paths: AppPaths | None = None) -> AppPaths:
    resolved = paths or resolve_app_paths()
    for directory in (
        resolved.data_dir,
        resolved.secrets_dir,
        resolved.logs_dir,
        resolved.backups_dir,
        resolved.exports_dir,
        resolved.tmp_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_directories() -> Path:
    return ensure_app_directories().root


def database_path() -> Path:
    return ensure_app_directories().database_path


def lock_path() -> Path:
    return ensure_app_directories().process_lock_path
