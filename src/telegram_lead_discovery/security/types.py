from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityPreflightResult:
    status: str  # passed | blocked
    checks: tuple[str, ...] = ()
    safe_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecretPresenceSnapshot:
    tg_api_id: bool
    tg_api_hash: bool
    tg_bot_token: bool
    tg_notify_chat_id: bool

    @property
    def telegram_ready(self) -> bool:
        return self.tg_api_id and self.tg_api_hash

    @property
    def notifications_ready(self) -> bool:
        return self.tg_bot_token and self.tg_notify_chat_id

    def missing_names(self) -> list[str]:
        mapping = {
            "TG_API_ID": self.tg_api_id,
            "TG_API_HASH": self.tg_api_hash,
            "TG_BOT_TOKEN": self.tg_bot_token,
            "TG_NOTIFY_CHAT_ID": self.tg_notify_chat_id,
        }
        return [name for name, present in mapping.items() if not present]
