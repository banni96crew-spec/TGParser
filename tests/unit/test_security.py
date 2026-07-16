"""Unit — security bind, secrets presence, redaction."""

from __future__ import annotations

import pytest

from telegram_lead_discovery.security.bind_guard import assert_loopback_bind
from telegram_lead_discovery.security.redaction import REDACTED, redact_event, redact_value
from telegram_lead_discovery.security.secrets import read_secret_presence


def test_at_sec_001_bind_rejection() -> None:
    with pytest.raises(ValueError):
        assert_loopback_bind("0.0.0.0")
    with pytest.raises(ValueError):
        assert_loopback_bind("::")
    with pytest.raises(ValueError):
        assert_loopback_bind("192.168.1.10")
    assert_loopback_bind("127.0.0.1")


def test_secret_presence_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "abc")
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_NOTIFY_CHAT_ID", raising=False)
    presence = read_secret_presence()
    assert presence.tg_api_id is True
    assert presence.tg_api_hash is True
    assert presence.tg_bot_token is False
    assert presence.telegram_ready is True
    assert presence.notifications_ready is False


def test_redaction_masks_sensitive() -> None:
    assert redact_value({"api_hash": "deadbeef", "safe": "ok"}) == {
        "api_hash": REDACTED,
        "safe": "ok",
    }
    text = redact_value("https://user:s3cret@example.com/x")
    assert "s3cret" not in text
    assert REDACTED in text
    assert redact_event({"bot_token": "123:ABC", "n": 1})["bot_token"] == REDACTED
