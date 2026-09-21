from __future__ import annotations

import pytest

from telegram_lead_discovery.infrastructure.windows_proxy import (
    TelegramProxyConfigurationError,
    resolve_telegram_connection,
)


def test_direct_mode_does_not_read_registry() -> None:
    def fail_reader() -> dict[str, object]:
        raise AssertionError("registry must not be read")

    result = resolve_telegram_connection("direct", registry_reader=fail_reader)

    assert result.route == "direct"
    assert result.proxy is None


def test_auto_uses_https_proxy_before_other_entries() -> None:
    result = resolve_telegram_connection(
        "auto",
        registry_reader=lambda: {
            "ProxyEnable": 1,
            "ProxyServer": "http=127.0.0.1:8080;https=127.0.0.1:10809;socks=127.0.0.1:1080",
        },
    )

    assert result.route == "system_proxy"
    assert result.proxy is not None
    assert result.proxy.proxy_type == "http"
    assert result.proxy.host == "127.0.0.1"
    assert result.proxy.port == 10809
    assert result.proxy.rdns is False


def test_auto_supports_authenticated_socks5() -> None:
    result = resolve_telegram_connection(
        "auto",
        registry_reader=lambda: {
            "ProxyEnable": 1,
            "ProxyServer": "socks=socks5://user:secret@proxy.local:1080",
        },
    )

    assert result.proxy is not None
    assert result.proxy.proxy_type == "socks5"
    assert result.proxy.username == "user"
    assert result.proxy.password == "secret"
    assert result.proxy.rdns is True


@pytest.mark.parametrize(
    "proxy_server",
    ["", "host", "host:0", "host:65536", "ftp://host:21", "http://host:80/path"],
)
def test_enabled_invalid_static_proxy_fails_closed(proxy_server: str) -> None:
    with pytest.raises(TelegramProxyConfigurationError, match="telegram_proxy_invalid"):
        resolve_telegram_connection(
            "auto",
            registry_reader=lambda: {
                "ProxyEnable": 1,
                "ProxyServer": proxy_server,
            },
        )


def test_disabled_proxy_and_pac_only_are_direct() -> None:
    disabled = resolve_telegram_connection(
        "auto",
        registry_reader=lambda: {"ProxyEnable": 0, "ProxyServer": "bad"},
    )
    pac_only = resolve_telegram_connection(
        "auto",
        registry_reader=lambda: {"ProxyEnable": 1, "AutoConfigURL": "http://pac.local"},
    )

    assert disabled.route == "direct"
    assert pac_only.route == "direct"
