"""Compatibility facade for the Telegram gateway contract (D-039)."""

from telegram_lead_discovery.collector.port_parts.errors import (
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySearchUnavailable,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
)
from telegram_lead_discovery.collector.port_parts.gateway import TelegramGateway
from telegram_lead_discovery.collector.port_parts.graph import (
    GraphEdgeDTO,
    GraphEdgeType,
    GraphSampleRequest,
)
from telegram_lead_discovery.collector.port_parts.messages import (
    HistoryRequest,
    TelegramMessageDTO,
    TelegramUpdateDTO,
)
from telegram_lead_discovery.collector.port_parts.search import (
    DirectorySearchRequest,
    GlobalSearchRequest,
    LinkedDiscussionDTO,
    PublicPostSearchQuotaDTO,
    PublicPostSearchRequest,
    SearchCursor,
    SearchMessageHitDTO,
    SearchPageDTO,
    SourceMessageSearchRequest,
)
from telegram_lead_discovery.collector.port_parts.sources import (
    AccountSnapshot,
    PublicSourceRef,
    SourceRef,
    SourceSnapshot,
    TelegramPeerRef,
)
