from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    """Raised when another process holds the application lock."""


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                old_pid = int(self.path.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                old_pid = 0
            if old_pid and _pid_alive(old_pid):
                raise AlreadyRunningError("already_running")
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self._held = True

    def release(self) -> None:
        if self._held and self.path.exists():
            try:
                if self.path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    self.path.unlink(missing_ok=True)
            finally:
                self._held = False


def is_runtime_running(path: Path | None = None) -> bool:
    """True when process lock file exists and the recorded PID is alive."""
    lock_file = path
    if lock_file is None:
        from telegram_lead_discovery.infrastructure.paths import lock_path

        lock_file = lock_path()
    if not lock_file.exists():
        return False
    try:
        pid = int(lock_file.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return False
    return _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except AttributeError:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        return True
