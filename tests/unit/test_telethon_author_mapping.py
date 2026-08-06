from __future__ import annotations

from types import SimpleNamespace

import pytest

from telegram_lead_discovery.collector.adapter.telethon_parts.author_mapping import (
    classify_message_author,
)


class PeerUser:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id


class PeerChannel:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id


class User:
    def __init__(self, *, bot: bool) -> None:
        self.bot = bot


class Channel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            SimpleNamespace(via_bot_id=None, from_id=PeerUser(10), sender=User(bot=False)),
            ("user", 10),
        ),
        (
            SimpleNamespace(via_bot_id=None, from_id=PeerUser(11), sender=User(bot=True)),
            ("bot", 11),
        ),
        (SimpleNamespace(via_bot_id=99, from_id=PeerUser(10), sender=User(bot=False)), ("bot", 99)),
        (
            SimpleNamespace(via_bot_id=None, from_id=PeerChannel(20), sender=Channel(20)),
            ("channel", 20),
        ),
        (
            SimpleNamespace(via_bot_id=None, from_id=None, sender=None, post_author="Admin"),
            ("anonymous", None),
        ),
        (SimpleNamespace(via_bot_id=None, from_id=None, sender=None), ("unknown", None)),
        (SimpleNamespace(via_bot_id=None, from_id=PeerUser(12), sender=None), ("unknown", 12)),
    ],
)
def test_closed_author_kind_mapping(message, expected) -> None:
    assert classify_message_author(message) == expected
