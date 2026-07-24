"""Adapter tests — Telethon Zero Stars + search mapping (AT-COL-022)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from telethon.tl.functions.channels import (
    CheckSearchPostsFloodRequest,
    GetFullChannelRequest,
    SearchPostsRequest,
)
from telethon.tl.functions.contacts import SearchRequest as ContactsSearchRequest
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.functions.messages import SearchRequest as MessagesSearchRequest

from telegram_lead_discovery.collector.adapter.telethon_gateway import (
    TelethonTelegramGateway,
)
from telegram_lead_discovery.collector.ports import (
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayInvalidSearchQuery,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewayUnauthorized,
    GlobalSearchRequest,
    PublicPostSearchRequest,
    SearchCursor,
    SourceMessageSearchRequest,
    SourceRef,
)


class _RecordingClient:
    """Minimal async Telethon client stand-in that records raw TL requests."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._handlers: dict[type, Any] = {}
        self._entities: dict[int, Any] = {}

    def on(self, request_type: type, response: Any) -> None:
        self._handlers[request_type] = response

    def register_entity(self, peer_id: int, entity: Any) -> None:
        self._entities[peer_id] = entity

    async def __call__(self, request: Any) -> Any:
        self.calls.append(request)
        for cls, response in self._handlers.items():
            if isinstance(request, cls):
                if isinstance(response, Exception):
                    raise response
                if callable(response) and not isinstance(response, type):
                    return response(request)
                return response
        raise AssertionError(f"unexpected request: {type(request).__name__}")

    async def get_input_entity(self, peer_id: int) -> Any:
        from telethon.tl.types import InputPeerChannel

        entity = self._entities.get(peer_id)
        if entity is None:
            return InputPeerChannel(channel_id=peer_id, access_hash=0)
        return InputPeerChannel(
            channel_id=int(entity.id),
            access_hash=int(getattr(entity, "access_hash", 0) or 0),
        )

    async def get_entity(self, peer_id: int) -> Any:
        entity = self._entities.get(peer_id)
        if entity is None:
            raise ValueError(f"unknown entity {peer_id}")
        return entity

    async def disconnect(self) -> None:
        return None


def _channel(*, telegram_id: int, username: str, title: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=telegram_id,
        username=username,
        title=title or username,
        broadcast=True,
        megagroup=False,
        access_hash=111,
    )


def _message(
    *,
    msg_id: int,
    channel_id: int,
    text: str,
    published: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id,
        message=text,
        date=published or datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        peer_id=SimpleNamespace(channel_id=channel_id),
    )


def _messages_page(*, messages: list[Any], chats: list[Any], next_rate: int | None = None) -> Any:
    return SimpleNamespace(messages=messages, chats=chats, next_rate=next_rate, users=[])


def _free_quota(*, remains: int = 3, stars_amount: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        total_daily=10,
        remains=remains,
        stars_amount=stars_amount,
        query_is_free=True,
        wait_till=None,
    )


def _paid_quota(*, stars_amount: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        total_daily=10,
        remains=0,
        stars_amount=stars_amount,
        query_is_free=False,
        wait_till=None,
    )


@pytest.mark.asyncio
async def test_search_public_posts_allow_paid_stars_is_none() -> None:
    client = _RecordingClient()
    channel = _channel(telegram_id=42, username="dev_jobs")
    client.on(CheckSearchPostsFloodRequest, _free_quota())
    client.on(
        SearchPostsRequest,
        _messages_page(
            messages=[_message(msg_id=7, channel_id=42, text="нужен разработчик сайта")],
            chats=[channel],
        ),
    )
    gw = TelethonTelegramGateway(client=client)

    page = await gw.search_public_posts(
        PublicPostSearchRequest(schema_version=1, query="нужен разработчик", limit=10)
    )

    search_calls = [c for c in client.calls if isinstance(c, SearchPostsRequest)]
    assert len(search_calls) == 1
    assert search_calls[0].allow_paid_stars is None
    assert len(page.hits) == 1
    assert page.hits[0].telegram_message_id == 7
    assert page.hits[0].source.username == "dev_jobs"


@pytest.mark.asyncio
async def test_search_public_posts_stars_required_does_not_call_search() -> None:
    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, _paid_quota(stars_amount=75))
    gw = TelethonTelegramGateway(client=client)

    with pytest.raises(GatewaySearchQuotaExhausted):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="нужен сайт", limit=10)
        )

    assert any(isinstance(c, CheckSearchPostsFloodRequest) for c in client.calls)
    assert not any(isinstance(c, SearchPostsRequest) for c in client.calls)


@pytest.mark.asyncio
async def test_check_public_post_search_quota_maps_free_slot() -> None:
    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, _free_quota(remains=2, stars_amount=0))
    gw = TelethonTelegramGateway(client=client)

    quota = await gw.check_public_post_search_quota("интеграция api")
    assert quota.free_slot_available is True
    assert quota.premium_required is False
    assert quota.stars_amount == 0


@pytest.mark.asyncio
async def test_search_global_maps_hits() -> None:
    client = _RecordingClient()
    channel = _channel(telegram_id=9, username="ru_dev")
    client.on(
        SearchGlobalRequest,
        _messages_page(
            messages=[_message(msg_id=3, channel_id=9, text="ищу разработчика")],
            chats=[channel],
            next_rate=100,
        ),
    )
    gw = TelethonTelegramGateway(client=client)

    page = await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="разработчик",
            groups_only=False,
            broadcasts_only=True,
            limit=20,
        )
    )
    assert len(page.hits) == 1
    assert page.truncated is True
    assert page.next_cursor is not None


@pytest.mark.asyncio
async def test_search_public_sources_directory() -> None:
    client = _RecordingClient()
    client.on(
        ContactsSearchRequest,
        SimpleNamespace(
            chats=[
                _channel(telegram_id=1, username="shop_dev", title="Shop Dev"),
                SimpleNamespace(id=2, username=None, title="Private", broadcast=True),
            ],
            users=[],
        ),
    )
    gw = TelethonTelegramGateway(client=client)
    sources = await gw.search_public_sources(
        DirectorySearchRequest(schema_version=1, query="shop", limit=10)
    )
    assert len(sources) == 1
    assert sources[0].username == "shop_dev"


@pytest.mark.asyncio
async def test_search_source_messages() -> None:
    client = _RecordingClient()
    channel = _channel(telegram_id=55, username="ops_chat")
    client.register_entity(55, channel)
    client.on(
        MessagesSearchRequest,
        _messages_page(
            messages=[_message(msg_id=11, channel_id=55, text="нужен telegram бот")],
            chats=[channel],
        ),
    )
    gw = TelethonTelegramGateway(client=client)
    page = await gw.search_source_messages(
        SourceMessageSearchRequest(
            schema_version=1,
            source=SourceRef(schema_version=1, source_id=1, telegram_id=55),
            query="бот",
            limit=10,
            cursor=SearchCursor(schema_version=1, token="0"),
        )
    )
    assert len(page.hits) == 1
    assert "бот" in page.hits[0].excerpt


@pytest.mark.asyncio
async def test_get_linked_discussion_public_only() -> None:
    client = _RecordingClient()
    parent = _channel(telegram_id=100, username="parent_ch")
    discussion = SimpleNamespace(
        id=200,
        username="parent_chat",
        title="Parent Discussion",
        broadcast=False,
        megagroup=True,
        access_hash=222,
    )
    client.register_entity(100, parent)
    client.on(
        GetFullChannelRequest,
        SimpleNamespace(
            full_chat=SimpleNamespace(linked_chat_id=200),
            chats=[parent, discussion],
        ),
    )
    gw = TelethonTelegramGateway(client=client)
    linked = await gw.get_linked_discussion(
        SourceRef(schema_version=1, source_id=1, telegram_id=100)
    )
    assert linked is not None
    assert linked.username == "parent_chat"
    assert linked.source_type == "megagroup"


@pytest.mark.asyncio
async def test_flood_wait_mapped_from_telethon() -> None:
    from telethon.errors import FloodWaitError

    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, FloodWaitError(request=None, capture=90))
    gw = TelethonTelegramGateway(client=client)

    with pytest.raises(GatewayFloodWait) as exc_info:
        await gw.check_public_post_search_quota("query")
    assert exc_info.value.until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_invalid_query_mapped() -> None:
    from telethon.errors import SearchQueryEmptyError

    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, _free_quota())
    client.on(SearchPostsRequest, SearchQueryEmptyError(request=None))
    gw = TelethonTelegramGateway(client=client)

    with pytest.raises(GatewayInvalidSearchQuery):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="", limit=5)
        )


@pytest.mark.asyncio
async def test_premium_required_mapped_on_search() -> None:
    from telethon.errors import PremiumAccountRequiredError

    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, _free_quota())
    client.on(SearchPostsRequest, PremiumAccountRequiredError(request=None))
    gw = TelethonTelegramGateway(client=client)

    with pytest.raises(GatewayPremiumRequired):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="нужен сайт", limit=5)
        )


@pytest.mark.asyncio
async def test_unauthorized_mapped() -> None:
    from telethon.errors import AuthKeyUnregisteredError

    client = _RecordingClient()
    client.on(CheckSearchPostsFloodRequest, AuthKeyUnregisteredError(request=None))
    gw = TelethonTelegramGateway(client=client)

    with pytest.raises(GatewayUnauthorized):
        await gw.check_public_post_search_quota("x")


def test_adapter_source_contains_allow_paid_stars_none_literal() -> None:
    from pathlib import Path

    import telegram_lead_discovery.collector.adapter.telethon_gateway as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "allow_paid_stars=None" in source
    assert "require_env" in source
    assert "os.environ" not in source


@pytest.mark.asyncio
async def test_search_global_groups_only_and_broadcasts_only_flags() -> None:
    client = _RecordingClient()
    megagroup = SimpleNamespace(
        id=41,
        username="mg_chat",
        title="MG",
        megagroup=True,
        broadcast=False,
        access_hash=1,
    )
    channel = _channel(telegram_id=42, username="bc_news")
    client.on(
        SearchGlobalRequest,
        _messages_page(
            messages=[
                _message(msg_id=1, channel_id=41, text="нужен сайт"),
                _message(msg_id=2, channel_id=42, text="нужен сайт"),
            ],
            chats=[megagroup, channel],
        ),
    )
    gw = TelethonTelegramGateway(client=client)

    await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="нужен сайт",
            groups_only=True,
            broadcasts_only=False,
            limit=10,
        )
    )
    assert len(client.calls) == 1
    req = client.calls[0]
    assert isinstance(req, SearchGlobalRequest)
    assert req.groups_only is True
    assert req.broadcasts_only is None

    client.calls.clear()
    await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="нужен сайт",
            groups_only=False,
            broadcasts_only=True,
            limit=10,
        )
    )
    req2 = client.calls[0]
    assert req2.broadcasts_only is True
    assert req2.groups_only is None


@pytest.mark.asyncio
async def test_search_hit_maps_megagroup_permalink_and_date() -> None:
    client = _RecordingClient()
    published = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    megagroup = SimpleNamespace(
        id=77,
        username="mega_dev",
        title="Mega Dev",
        megagroup=True,
        broadcast=False,
        access_hash=9,
    )
    client.on(
        SearchGlobalRequest,
        _messages_page(
            messages=[
                _message(
                    msg_id=5,
                    channel_id=77,
                    text="ищу разработчика",
                    published=published,
                )
            ],
            chats=[megagroup],
        ),
    )
    gw = TelethonTelegramGateway(client=client)
    page = await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="разработчик",
            groups_only=True,
            broadcasts_only=False,
            limit=10,
        )
    )
    assert len(page.hits) == 1
    hit = page.hits[0]
    assert hit.source.source_type == "megagroup"
    assert hit.source.username == "mega_dev"
    assert hit.permalink == "https://t.me/mega_dev/5"
    assert hit.published_at == published
    assert hit.telegram_message_id == 5
