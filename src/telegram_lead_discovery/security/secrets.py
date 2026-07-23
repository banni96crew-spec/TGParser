from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from telegram_lead_discovery.security.session_paths import app_root
from telegram_lead_discovery.security.types import SecretPresenceSnapshot

SECRET_ENV_NAMES = (
    "TG_API_ID",
    "TG_API_HASH",
    "TG_BOT_TOKEN",
    "TG_NOTIFY_CHAT_ID",
)


def secret_file_path(name: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else app_root()
    return base / "secrets" / name


def _present(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name)
    return bool(value and str(value).strip())


def _read_secret_file(name: str, *, root: Path | None = None) -> str | None:
    path = secret_file_path(name, root=root)
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def resolve_secret(
    name: str,
    env: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> str | None:
    """Resolve a secret with environment priority over the ACL-protected file (SET-008)."""
    source = env if env is not None else os.environ
    value = source.get(name)
    if value and str(value).strip():
        return str(value).strip()
    return _read_secret_file(name, root=root)


def hydrate_environ_from_secret_files(*, root: Path | None = None) -> tuple[str, ...]:
    """Load missing SECRET_ENV_NAMES from secrets dir into process environ.

    Environment values always win. Returns names that were hydrated from files.
    """
    loaded: list[str] = []
    for name in SECRET_ENV_NAMES:
        if _present(os.environ, name):
            continue
        value = _read_secret_file(name, root=root)
        if value is None:
            continue
        os.environ[name] = value
        loaded.append(name)
    return tuple(loaded)


def load_secret_presence(
    env: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> SecretPresenceSnapshot:
    source = env if env is not None else os.environ

    def present(name: str) -> bool:
        if _present(source, name):
            return True
        # Explicit env mapping without root stays mapping-only (test isolation).
        # File fallback applies for process environ or when root is provided (AT-SET-008).
        if env is not None and root is None:
            return False
        return _read_secret_file(name, root=root) is not None

    return SecretPresenceSnapshot(
        tg_api_id=present("TG_API_ID"),
        tg_api_hash=present("TG_API_HASH"),
        tg_bot_token=present("TG_BOT_TOKEN"),
        tg_notify_chat_id=present("TG_NOTIFY_CHAT_ID"),
    )


def read_secret_presence() -> SecretPresenceSnapshot:
    return load_secret_presence()


def require_env(name: str) -> str:
    value = resolve_secret(name)
    if not value:
        raise KeyError(name)
    return value
