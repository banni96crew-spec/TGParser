from __future__ import annotations

import os
from collections.abc import Mapping

from telegram_lead_discovery.security.types import SecretPresenceSnapshot

SECRET_ENV_NAMES = (
    "TG_API_ID",
    "TG_API_HASH",
    "TG_BOT_TOKEN",
    "TG_NOTIFY_CHAT_ID",
)


def _present(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name)
    return bool(value and str(value).strip())


def load_secret_presence(env: Mapping[str, str] | None = None) -> SecretPresenceSnapshot:
    source = env if env is not None else os.environ
    return SecretPresenceSnapshot(
        tg_api_id=_present(source, "TG_API_ID"),
        tg_api_hash=_present(source, "TG_API_HASH"),
        tg_bot_token=_present(source, "TG_BOT_TOKEN"),
        tg_notify_chat_id=_present(source, "TG_NOTIFY_CHAT_ID"),
    )


def read_secret_presence() -> SecretPresenceSnapshot:
    return load_secret_presence()


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise KeyError(name)
    return value
