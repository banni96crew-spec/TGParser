from __future__ import annotations

from datetime import UTC, datetime, timedelta

from telegram_lead_discovery.collector.ports import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySearchUnavailable,
    GatewaySourceInaccessible,
    GatewayTimeout,
    GatewayTransientError,
    GatewayUnauthorized,
    RequestControlError,
)


def _raise_mapped(exc: BaseException) -> BaseException:
    if isinstance(
        exc,
        RequestControlError
        | GatewayFloodWait
        | GatewayFrozen
        | GatewayInvalidSearchQuery
        | GatewayPermanentError
        | GatewayPremiumRequired
        | GatewaySearchQuotaExhausted
        | GatewaySearchUnavailable
        | GatewaySourceInaccessible
        | GatewayTimeout
        | GatewayTransientError
        | GatewayUnauthorized,
    ):
        return exc
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

    flood_types = tuple(
        cls
        for cls in (
            getattr(te, "FloodWaitError", None),
            getattr(te, "FloodPremiumWaitError", None),
            getattr(te, "FloodTestPhoneWaitError", None),
            getattr(te, "SlowModeWaitError", None),
            getattr(te, "PeerFloodError", None),
        )
        if cls is not None
    )
    if flood_types and isinstance(exc, flood_types):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=max(seconds, 1)))

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

    inaccessible_types = tuple(
        cls
        for cls in (
            te.ChannelPrivateError,
            te.ChatForbiddenError,
            getattr(te, "UsernameNotOccupiedError", None),
            getattr(te, "ChannelInvalidError", None),
        )
        if cls is not None
    )
    if inaccessible_types and isinstance(exc, inaccessible_types):
        # #region agent log
        import json as _json
        import time as _time
        from pathlib import Path as _Path
        try:
            with _Path(r"c:\Users\Николай\Desktop\Telegram Parser\debug-1c5371.log").open(
                "a", encoding="utf-8"
            ) as _f:
                _f.write(_json.dumps({"sessionId":"1c5371","hypothesisId":"H3","location":"error_mapping.py:_map_telethon_error","message":"mapped_inaccessible","data":{"exc":type(exc).__name__},"timestamp":int(_time.time()*1000),"runId":"post-fix"})+"\n")
        except Exception:
            pass
        # #endregion
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
        if "FLOOD" in message or "TOO MANY REQUESTS" in message:
            seconds = int(getattr(exc, "seconds", 0) or 0)
            return GatewayFloodWait(datetime.now(UTC) + timedelta(seconds=max(seconds, 1)))
        if any(
            token in message
            for token in (
                "USERNAME_NOT_OCCUPIED",
                "CHANNEL_PRIVATE",
                "CHANNEL_INVALID",
                "CHAT_FORBIDDEN",
            )
        ):
            return GatewaySourceInaccessible(str(exc))
        if getattr(exc, "code", None) in {400, 403}:
            return GatewayPermanentError(str(exc))
        if getattr(exc, "code", None) in {500, 503}:
            return GatewayTransientError(str(exc))

    return None
