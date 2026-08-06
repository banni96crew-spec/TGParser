from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchUnavailable,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
)


def _raise_mapped(exc: BaseException) -> BaseException:
    mapped = _map_telethon_error(exc)
    if mapped is not None:
        return mapped
    return GatewayTransientError(str(exc))


def _map_telethon_error(exc: BaseException) -> Exception | None:
    """Map Telethon/RPC errors to gateway domain exceptions."""
    try:
        from telethon import errors as te
    except ImportError:  # pragma: no cover
        return None

    if isinstance(exc, te.FloodWaitError):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=seconds))
    if isinstance(exc, getattr(te, "FloodPremiumWaitError", ())):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=seconds))

    if isinstance(
        exc,
        te.AuthKeyError
        | te.AuthKeyUnregisteredError
        | te.SessionExpiredError
        | te.SessionRevokedError
        | te.UnauthorizedError,
    ):
        return GatewayUnauthorized(str(exc))

    frozen_cls = getattr(te, "FrozenMethodInvalidError", None)
    if frozen_cls is not None and isinstance(exc, frozen_cls):
        return GatewayFrozen(str(exc))

    if isinstance(exc, te.ChannelPrivateError | te.ChatForbiddenError):
        return GatewaySourceInaccessible(str(exc))

    premium_cls = getattr(te, "PremiumAccountRequiredError", None)
    if premium_cls is not None and isinstance(exc, premium_cls):
        return GatewayPremiumRequired(str(exc))

    if isinstance(exc, te.QueryTooShortError | te.SearchQueryEmptyError):
        return GatewayInvalidSearchQuery(str(exc))

    unavailable_cls = getattr(te, "SearchWithLinkNotSupportedError", None)
    if unavailable_cls is not None and isinstance(exc, unavailable_cls):
        return GatewaySearchUnavailable(str(exc))

    if isinstance(exc, te.ServerError | te.TimedOutError):
        return GatewayTransientError(str(exc))

    if isinstance(exc, te.RPCError):
        message = (getattr(exc, "message", "") or str(exc)).upper()
        if "PREMIUM" in message:
            return GatewayPremiumRequired(str(exc))
        if "FLOOD" in message:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=max(seconds, 1)))
        if getattr(exc, "code", None) in {400, 403}:
            return GatewayPermanentError(str(exc))
        if getattr(exc, "code", None) in {500, 503}:
            return GatewayTransientError(str(exc))

    return None
