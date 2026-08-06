from __future__ import annotations

from datetime import datetime


class GatewayFloodWait(Exception):
    def __init__(self, until: datetime) -> None:
        self.until = until
        super().__init__(f"flood_wait_until={until.isoformat()}")


class GatewayUnauthorized(Exception):
    pass


class GatewayFrozen(Exception):
    pass


class GatewaySourceInaccessible(Exception):
    pass


class GatewayTransientError(Exception):
    pass


class GatewayPermanentError(Exception):
    pass


class GatewayPremiumRequired(Exception):
    pass


class GatewaySearchQuotaExhausted(Exception):
    pass


class GatewayInvalidSearchQuery(Exception):
    pass


class GatewaySearchUnavailable(Exception):
    pass
