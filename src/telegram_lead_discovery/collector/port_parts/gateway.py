from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from telegram_lead_discovery.collector.port_parts.graph import (
    GraphEdgeDTO,
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
    PublicPostSearchQuotaDTO,
    PublicPostSearchRequest,
    SearchPageDTO,
    SourceMessageSearchRequest,
)
from telegram_lead_discovery.collector.port_parts.sources import (
    AccountSnapshot,
    PublicSourceRef,
    SourceRef,
    SourceSnapshot,
)


class TelegramGateway(Protocol):
    async def connect(self) -> AccountSnapshot: ...

    async def disconnect(self) -> None: ...

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot: ...

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot: ...

    async def get_recommendations(self, source: SourceRef, limit: int) -> list[SourceSnapshot]: ...

    def iter_history(self, request: HistoryRequest) -> AsyncIterator[TelegramMessageDTO]: ...

    def iter_updates(self) -> AsyncIterator[TelegramUpdateDTO]: ...

    async def get_message(
        self, source: SourceRef, message_id: int
    ) -> TelegramMessageDTO | None: ...

    async def search_global(self, request: GlobalSearchRequest) -> SearchPageDTO: ...

    async def search_public_sources(
        self, request: DirectorySearchRequest
    ) -> list[SourceSnapshot]: ...

    async def check_public_post_search_quota(self, query: str) -> PublicPostSearchQuotaDTO: ...

    async def search_public_posts(self, request: PublicPostSearchRequest) -> SearchPageDTO: ...

    async def search_source_messages(
        self, request: SourceMessageSearchRequest
    ) -> SearchPageDTO: ...

    async def get_linked_discussion(self, source: SourceRef) -> SourceSnapshot | None: ...

    async def sample_public_graph_edges(
        self, request: GraphSampleRequest
    ) -> list[GraphEdgeDTO]: ...
