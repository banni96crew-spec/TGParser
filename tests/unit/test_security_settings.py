"""Unit tests — security bind/secrets + settings defaults."""

from __future__ import annotations

import pytest

from telegram_lead_discovery.security.bind_guard import BindAddressRejected, assert_loopback_bind
from telegram_lead_discovery.security.secrets import load_secret_presence
from telegram_lead_discovery.settings.defaults import DEFAULT_SETTINGS


def test_bind_loopback_only() -> None:
    assert assert_loopback_bind("127.0.0.1") == "127.0.0.1"
    with pytest.raises(BindAddressRejected):
        assert_loopback_bind("0.0.0.0")


def test_delivery_mode_default_shadow() -> None:
    assert DEFAULT_SETTINGS["notifications.delivery_mode"][1] == "shadow"


def test_secret_presence_no_values() -> None:
    presence = load_secret_presence({"TG_API_ID": "1", "TG_API_HASH": "h"})
    assert presence.telegram_ready is True
    assert presence.notifications_ready is False
    assert "TG_BOT_TOKEN" in presence.missing_names()
