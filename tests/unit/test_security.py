"""Unit — security bind, secrets presence, redaction."""

from __future__ import annotations

import os

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


def test_secret_presence_only(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "abc")
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_NOTIFY_CHAT_ID", raising=False)
    # Isolate from operator secret files under real LOCALAPPDATA.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    presence = read_secret_presence()
    assert presence.tg_api_id is True
    assert presence.tg_api_hash is True
    assert presence.tg_bot_token is False
    assert presence.telegram_ready is True
    assert presence.notifications_ready is False


def test_at_set_008_env_overrides_secret_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from telegram_lead_discovery.security.secrets import (
        hydrate_environ_from_secret_files,
        load_secret_presence,
        resolve_secret,
    )

    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "TG_API_ID").write_text("from-file", encoding="utf-8")
    (secrets / "TG_API_HASH").write_text("hash-file", encoding="utf-8")
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)

    presence = load_secret_presence({}, root=tmp_path)
    assert presence.telegram_ready is True
    assert resolve_secret("TG_API_ID", {}, root=tmp_path) == "from-file"

    monkeypatch.setenv("TG_API_ID", "from-env")
    assert resolve_secret("TG_API_ID", root=tmp_path) == "from-env"
    loaded = hydrate_environ_from_secret_files(root=tmp_path)
    assert "TG_API_ID" not in loaded
    assert "TG_API_HASH" in loaded
    assert os.environ["TG_API_HASH"] == "hash-file"


def test_redaction_masks_sensitive() -> None:
    assert redact_value({"api_hash": "deadbeef", "safe": "ok"}) == {
        "api_hash": REDACTED,
        "safe": "ok",
    }
    text = redact_value("https://user:s3cret@example.com/x")
    assert "s3cret" not in text
    assert REDACTED in text
    assert redact_event({"bot_token": "123:ABC", "n": 1})["bot_token"] == REDACTED
