"""D-074: v8 must not run directory replacement."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from telegram_lead_discovery.source_discovery.worker_parts.replacement import (
    _expand_directory_replacement,
)


@pytest.mark.asyncio
async def test_v8_directory_replacement_is_noop() -> None:
    ctx = SimpleNamespace(profile_version=SimpleNamespace(version=8))
    fetched, ids = await _expand_directory_replacement(
        ctx,
        suppressed_ids={1, 2},
        target_quota=25,
        already_qualified=0,
    )
    assert fetched == 0
    assert ids == []
