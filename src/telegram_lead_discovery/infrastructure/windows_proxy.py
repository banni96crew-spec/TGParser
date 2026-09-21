"""Resolve the Telegram transport from the current Windows user proxy settings."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote, urlsplit


class TelegramProxyConfigurationError(ValueError):
    """Enabled system proxy is present but cannot be used safely."""

    reason_code = "telegram_proxy_invalid"

    def __init__(self) -> None:
        super().__init__(self.reason_code)


@dataclass(frozen=True, slots=True)
class TelegramProxyConfig:
    proxy_type: Literal["http", "socks5", "socks4"]
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    rdns: bool = True

    def as_telethon_proxy(self) -> dict[str, Any]:
        return {
            "proxy_type": self.proxy_type,
            "addr": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": self.rdns,
        }


@dataclass(frozen=True, slots=True)
class TelegramConnectionConfig:
    route: Literal["direct", "system_proxy"]
    proxy: TelegramProxyConfig | None = None

    @classmethod
    def direct(cls) -> TelegramConnectionConfig:
        return cls(route="direct")


RegistryReader = Callable[[], Mapping[str, Any]]


def _read_wininet_settings() -> Mapping[str, Any]:
    if sys.platform != "win32":
        return {}
    import winreg

    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            values: dict[str, Any] = {}
            for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL"):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    pass
            return values
    except FileNotFoundError:
        return {}


def _select_proxy(raw: str) -> tuple[str, str]:
    entries = [item.strip() for item in raw.split(";") if item.strip()]
    keyed: dict[str, str] = {}
    single: str | None = None
    for entry in entries:
        if "=" in entry:
            key, value = entry.split("=", 1)
            keyed[key.strip().lower()] = value.strip()
        elif single is None:
            single = entry
    for key in ("https", "http", "socks"):
        if keyed.get(key):
            return key, keyed[key]
    if single:
        return "single", single
    raise TelegramProxyConfigurationError()


def _parse_proxy(kind: str, endpoint: str) -> TelegramProxyConfig:
    value = endpoint.strip()
    if not value or any(char.isspace() for char in value):
        raise TelegramProxyConfigurationError()
    default_scheme = "socks5" if kind == "socks" else "http"
    parsed = urlsplit(value if "://" in value else f"{default_scheme}://{value}")
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "socks5", "socks4"}:
        raise TelegramProxyConfigurationError()
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise TelegramProxyConfigurationError() from exc
    if (
        not host
        or port is None
        or not 1 <= port <= 65535
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise TelegramProxyConfigurationError()
    return TelegramProxyConfig(
        proxy_type=scheme,  # type: ignore[arg-type]
        host=host,
        port=port,
        username=unquote(parsed.username) if parsed.username is not None else None,
        password=unquote(parsed.password) if parsed.password is not None else None,
        rdns=scheme.startswith("socks"),
    )


def resolve_telegram_connection(
    mode: str,
    *,
    registry_reader: RegistryReader | None = None,
) -> TelegramConnectionConfig:
    if mode == "direct":
        return TelegramConnectionConfig.direct()
    if mode != "auto":
        raise TelegramProxyConfigurationError()
    values = (registry_reader or _read_wininet_settings)()
    if values.get("ProxyEnable") != 1:
        return TelegramConnectionConfig.direct()
    raw = values.get("ProxyServer")
    if not isinstance(raw, str) or not raw.strip():
        # PAC/WPAD is intentionally not interpreted by the MVP.
        if values.get("AutoConfigURL"):
            return TelegramConnectionConfig.direct()
        raise TelegramProxyConfigurationError()
    kind, endpoint = _select_proxy(raw)
    return TelegramConnectionConfig(
        route="system_proxy",
        proxy=_parse_proxy(kind, endpoint),
    )


__all__ = [
    "TelegramConnectionConfig",
    "TelegramProxyConfig",
    "TelegramProxyConfigurationError",
    "resolve_telegram_connection",
]
