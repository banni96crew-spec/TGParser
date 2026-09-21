from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import GatewayPermanentError
from telegram_lead_discovery.infrastructure.windows_proxy import (
    TelegramConnectionConfig,
    TelegramProxyConfig,
)


@pytest.mark.asyncio
async def test_gateway_passes_system_proxy_to_telethon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "hash")
    client = AsyncMock()
    client.get_me.return_value = type("Me", (), {"id": 7, "username": "operator"})()
    config = TelegramConnectionConfig(
        route="system_proxy",
        proxy=TelegramProxyConfig("http", "127.0.0.1", 10809, rdns=False),
    )

    with (
        patch(
            "telegram_lead_discovery.collector.adapter.telethon_gateway.load_secret_presence"
        ) as presence,
        patch(
            "telegram_lead_discovery.collector.adapter.controlled_client.ControlledTelegramClient",
            return_value=client,
        ) as constructor,
        patch("importlib.util.find_spec", return_value=object()),
    ):
        presence.return_value.telegram_ready = True
        account = await TelethonTelegramGateway(connection_config=config).connect()

    assert account.connected is True
    assert constructor.call_args.kwargs["proxy"] == {
        "proxy_type": "http",
        "addr": "127.0.0.1",
        "port": 10809,
        "username": None,
        "password": None,
        "rdns": False,
    }


@pytest.mark.asyncio
async def test_proxy_dependency_failure_has_safe_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "hash")
    config = TelegramConnectionConfig(
        route="system_proxy",
        proxy=TelegramProxyConfig("http", "secret.proxy", 10809),
    )
    with (
        patch(
            "telegram_lead_discovery.collector.adapter.telethon_gateway.load_secret_presence"
        ) as presence,
        patch("importlib.util.find_spec", return_value=None),
    ):
        presence.return_value.telegram_ready = True
        with pytest.raises(
            GatewayPermanentError, match="telegram_proxy_dependency_missing"
        ):
            await TelethonTelegramGateway(connection_config=config).connect()
