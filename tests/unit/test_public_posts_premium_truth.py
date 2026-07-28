"""Public posts Premium vs Stars quota truth (SRC-049 / D-068)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from telegram_lead_discovery.collector.fake import FakeTelegramGateway
from telegram_lead_discovery.collector.ports import (
    GatewayPremiumRequired,
    PublicPostSearchRequest,
)
from telegram_lead_discovery.dashboard.discovery_routes import _quota_summary


@pytest.mark.asyncio
async def test_premium_required_truth_not_hardcoded_false() -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=False, premium_required=True, stars_amount=0)
    quota = await gw.check_public_post_search_quota("нужен сайт")
    assert quota.premium_required is True
    assert quota.free_slot_available is False


@pytest.mark.asyncio
async def test_stars_quota_exhausted_distinct_from_premium() -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=False, premium_required=False, stars_amount=100)
    quota = await gw.check_public_post_search_quota("нужен сайт")
    assert quota.premium_required is False
    assert quota.stars_amount == 100
    with pytest.raises(Exception) as excinfo:
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="нужен сайт", limit=10)
        )
    # Zero Stars path refuses paid slot
    assert "quota" in type(excinfo.value).__name__.lower() or "Quota" in type(
        excinfo.value
    ).__name__


@pytest.mark.asyncio
async def test_premium_error_on_search_is_premium_required() -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=True, premium_required=False, stars_amount=0)
    gw._raise_premium_on_public_posts = True
    with pytest.raises(GatewayPremiumRequired):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="нужен сайт", limit=10)
        )
    _ = datetime.now(UTC) + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_quota_ui_does_not_promise_free_from_check_alone() -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=True, premium_required=False, stars_amount=0)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(gateway=gw)))
    summary = await _quota_summary(request)  # type: ignore[arg-type]
    assert "confirms on search" in summary["label"]
    assert "бесплатный слот доступен" not in summary["label"]


@pytest.mark.asyncio
async def test_quota_ui_premium_required_label() -> None:
    gw = FakeTelegramGateway()
    gw.set_quota(free_slot_available=False, premium_required=True, stars_amount=0)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(gateway=gw)))
    summary = await _quota_summary(request)  # type: ignore[arg-type]
    assert summary["premium_required"] is True
    assert "Premium" in summary["label"]
