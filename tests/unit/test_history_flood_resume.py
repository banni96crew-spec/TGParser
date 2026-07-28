"""Focused FloodWait resume + history verification helpers (SRC-048)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    HistoryRequest,
    TelegramPeerRef,
)
from telegram_lead_discovery.source_discovery.worker import (
    HISTORY_SCAN_QUERY_TEXT,
    _TERMINAL_VERIFICATION_STATES,
    _load_history_cursor,
)


@pytest.mark.asyncio
async def test_history_flood_wait_persists_cursor_token() -> None:
    until = datetime.now(UTC) + timedelta(minutes=5)
    gw = FakeTelegramGateway()
    gw.set_flood_wait(until, "iter_history")
    req = HistoryRequest(
        schema_version=1,
        source_id=0,
        peer=TelegramPeerRef(schema_version=1, telegram_peer_id=1001),
        limit=10,
        purpose="scouting_verification",
        continuation_cursor="42",
    )
    with pytest.raises(GatewayFloodWait) as excinfo:
        async for _ in gw.iter_history(req):
            pass
    assert excinfo.value.until == until
    assert gw.history_calls[0].continuation_cursor == "42"
    assert gw.history_calls[0].purpose == "scouting_verification"


def test_history_cursor_roundtrip_helper() -> None:
    class _Q:
        cursor_json = json.dumps(
            {
                "offset_id": 42,
                "scanned": 12,
                "distinct_hashes": ["a", "b"],
                "noise_kept": 1,
                "stop_reason": "flood_wait",
            }
        )

    cursor = _load_history_cursor(_Q())  # type: ignore[arg-type]
    assert cursor["offset_id"] == 42
    assert cursor["scanned"] == 12
    assert HISTORY_SCAN_QUERY_TEXT == "history_scan"


def test_terminal_verification_states_exclude_running_retry() -> None:
    assert "succeeded" in _TERMINAL_VERIFICATION_STATES
    assert "failed" in _TERMINAL_VERIFICATION_STATES
    assert "running" not in _TERMINAL_VERIFICATION_STATES
    assert "retry_wait" not in _TERMINAL_VERIFICATION_STATES
