"""Unit — infrastructure bind, lock, frozen deps."""

from __future__ import annotations

from pathlib import Path

import pytest

from telegram_lead_discovery.infrastructure.paths import ensure_directories, lock_path
from telegram_lead_discovery.infrastructure.process_lock import ProcessLock
from telegram_lead_discovery.security.bind_guard import assert_loopback_bind


def test_at_inf_001_frozen_deps_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (root / "pyproject.toml").is_file()
    assert (root / "uv.lock").is_file()
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12,<3.13"' in text
    assert "telethon==1.44.0" in text


def test_at_inf_005_bind_loopback_only() -> None:
    assert_loopback_bind("127.0.0.1")
    with pytest.raises(ValueError):
        assert_loopback_bind("0.0.0.0")


def test_at_inf_010_process_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ensure_directories()
    path = lock_path()
    lock_a = ProcessLock(path)
    lock_a.acquire()
    lock_b = ProcessLock(path)
    with pytest.raises(RuntimeError, match="already_running"):
        lock_b.acquire()
    lock_a.release()
    lock_b.acquire()
    lock_b.release()


def test_inf_006_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = ensure_directories()
    for name in ("data", "secrets", "logs", "backups", "exports", "tmp"):
        assert (root / name).is_dir()
