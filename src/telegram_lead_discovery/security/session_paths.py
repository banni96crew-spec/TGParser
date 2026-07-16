from __future__ import annotations

import os
from pathlib import Path


def app_root() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("TLD_DATA_ROOT")
    if not local:
        raise RuntimeError("LOCALAPPDATA or TLD_DATA_ROOT is required")
    return Path(local) / "TelegramLeadDiscovery"


def session_path() -> Path:
    return app_root() / "secrets" / "telegram.session"
