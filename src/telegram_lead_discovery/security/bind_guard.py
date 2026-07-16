from __future__ import annotations


class BindAddressRejected(ValueError):
    """Raised when bind host is not loopback 127.0.0.1 (SEC-001)."""


def assert_loopback_bind(host: str) -> str:
    if host != "127.0.0.1":
        raise BindAddressRejected(f"bind address must be 127.0.0.1, got {host!r}")
    return host
