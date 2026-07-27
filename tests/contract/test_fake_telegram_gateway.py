"""Contract tests — FakeTelegramGateway keyword-search matrix (AT-COL-021)."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from telegram_lead_discovery.collector.fake import (
    FakeTelegramGateway,
    make_hit,
    make_source,
)
from telegram_lead_discovery.collector.ports import (
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySourceInaccessible,
    GlobalSearchRequest,
    PublicPostSearchRequest,
    PublicSourceRef,
    SearchCursor,
    SourceMessageSearchRequest,
    SourceRef,
)


def _gateway() -> FakeTelegramGateway:
    return FakeTelegramGateway()


# --- DTO / Zero Stars invariants ------------------------------------------------


def test_public_post_search_request_has_no_allow_paid_stars() -> None:
    names = {f.name for f in fields(PublicPostSearchRequest)}
    assert "allow_paid_stars" not in names


def test_fake_gateway_module_has_no_allow_paid_stars() -> None:
    from pathlib import Path

    import telegram_lead_discovery.collector.fake as fake_mod

    source = Path(fake_mod.__file__).read_text(encoding="utf-8")
    assert "allow_paid_stars" not in source
    assert "from telethon" not in source
    assert "import telethon" not in source
    assert "TelegramClient" not in source


# --- Global groups / broadcast search -------------------------------------------


@pytest.mark.asyncio
async def test_search_global_groups_only() -> None:
    gw = _gateway()
    group = make_source(telegram_id=1, username="dev_chat", source_type="megagroup")
    channel = make_source(telegram_id=2, username="dev_news", source_type="channel")
    gw.set_global_hits(
        [
            make_hit(source=group, message_id=10, excerpt="нужен разработчик сайта"),
            make_hit(source=channel, message_id=20, excerpt="нужен разработчик сайта"),
        ]
    )
    page = await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="разработчик",
            groups_only=True,
            limit=50,
        )
    )
    assert len(page.hits) == 1
    assert page.hits[0].source.source_type == "megagroup"
    assert page.hits[0].telegram_message_id == 10


@pytest.mark.asyncio
async def test_search_global_broadcasts_only() -> None:
    gw = _gateway()
    group = make_source(telegram_id=1, username="dev_chat", source_type="group")
    channel = make_source(telegram_id=2, username="dev_news", source_type="channel")
    gw.set_global_hits(
        [
            make_hit(source=group, message_id=10, excerpt="ищу разработчика"),
            make_hit(source=channel, message_id=20, excerpt="ищу разработчика"),
        ]
    )
    page = await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="разработчика",
            broadcasts_only=True,
            limit=50,
        )
    )
    assert len(page.hits) == 1
    assert page.hits[0].source.source_type == "channel"
    assert page.hits[0].telegram_message_id == 20


# --- Directory search -----------------------------------------------------------


@pytest.mark.asyncio
async def test_directory_search() -> None:
    gw = _gateway()
    a = make_source(telegram_id=11, username="shop_devs", title="Shop Devs")
    b = make_source(telegram_id=12, username="random_chat", title="Random")
    gw.set_directory_results([a, b])
    results = await gw.search_public_sources(
        DirectorySearchRequest(schema_version=1, query="shop", limit=10)
    )
    assert results == [a]


# --- Per-source search ----------------------------------------------------------


@pytest.mark.asyncio
async def test_per_source_search() -> None:
    gw = _gateway()
    src = make_source(telegram_id=100, username="target_chan")
    gw.set_source_message_hits(
        100,
        [
            make_hit(source=src, message_id=1, excerpt="нужен бот"),
            make_hit(source=src, message_id=2, excerpt="погода сегодня"),
            make_hit(source=src, message_id=3, excerpt="нужен сайт"),
        ],
    )
    page = await gw.search_source_messages(
        SourceMessageSearchRequest(
            schema_version=1,
            source=SourceRef(schema_version=1, source_id=1, telegram_id=100),
            query="нужен",
            limit=50,
        )
    )
    assert [h.telegram_message_id for h in page.hits] == [1, 3]


# --- Public posts pagination ----------------------------------------------------


@pytest.mark.asyncio
async def test_public_posts_pagination() -> None:
    gw = _gateway()
    gw.set_page_size(2)
    src = make_source(telegram_id=200, username="posts_chan")
    hits = [
        make_hit(source=src, message_id=i, excerpt=f"нужен сайт #{i}")
        for i in range(1, 6)
    ]
    gw.set_public_post_hits("нужен сайт", hits)
    gw.set_quota(free_slot_available=True, stars_amount=0)

    page1 = await gw.search_public_posts(
        PublicPostSearchRequest(schema_version=1, query="нужен сайт", limit=2)
    )
    assert len(page1.hits) == 2
    assert page1.truncated is True
    assert page1.next_cursor is not None
    assert [h.telegram_message_id for h in page1.hits] == [1, 2]

    page2 = await gw.search_public_posts(
        PublicPostSearchRequest(
            schema_version=1,
            query="нужен сайт",
            limit=2,
            cursor=page1.next_cursor,
        )
    )
    assert [h.telegram_message_id for h in page2.hits] == [3, 4]
    assert page2.next_cursor is not None

    page3 = await gw.search_public_posts(
        PublicPostSearchRequest(
            schema_version=1,
            query="нужен сайт",
            limit=2,
            cursor=page2.next_cursor,
        )
    )
    assert [h.telegram_message_id for h in page3.hits] == [5]
    assert page3.next_cursor is None
    assert page3.truncated is False


# --- Free quota / Premium / quota exhausted -------------------------------------


@pytest.mark.asyncio
async def test_free_quota_allows_public_posts() -> None:
    gw = _gateway()
    src = make_source(telegram_id=201, username="free_chan")
    gw.set_quota(free_slot_available=True, premium_required=False, stars_amount=0)
    gw.set_public_post_hits(
        "сайт", [make_hit(source=src, message_id=7, excerpt="нужен сайт")]
    )
    quota = await gw.check_public_post_search_quota("сайт")
    assert quota.free_slot_available is True
    assert quota.stars_amount == 0
    page = await gw.search_public_posts(
        PublicPostSearchRequest(schema_version=1, query="сайт", limit=10)
    )
    assert len(page.hits) == 1


@pytest.mark.asyncio
async def test_premium_required_raises() -> None:
    gw = _gateway()
    gw.set_quota(free_slot_available=False, premium_required=True, stars_amount=0)
    quota = await gw.check_public_post_search_quota("сайт")
    assert quota.premium_required is True
    with pytest.raises(GatewayPremiumRequired):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="сайт", limit=10)
        )


@pytest.mark.asyncio
async def test_quota_exhausted_raises() -> None:
    gw = _gateway()
    gw.set_quota(free_slot_available=False, premium_required=False, stars_amount=25)
    quota = await gw.check_public_post_search_quota("сайт")
    assert quota.free_slot_available is False
    assert quota.stars_amount == 25
    with pytest.raises(GatewaySearchQuotaExhausted):
        await gw.search_public_posts(
            PublicPostSearchRequest(schema_version=1, query="сайт", limit=10)
        )
    # Stars path must not invent paid execution — only the raise above.
    assert len(gw.search_public_posts_calls) == 1


# --- FloodWait ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flood_wait() -> None:
    gw = _gateway()
    until = datetime(2026, 7, 23, 12, 0, tzinfo=UTC) + timedelta(seconds=90)
    gw.set_flood_wait(until, "search_global")
    with pytest.raises(GatewayFloodWait) as exc:
        await gw.search_global(
            GlobalSearchRequest(schema_version=1, query="сайт", limit=10)
        )
    assert exc.value.until == until


# --- Inaccessible source --------------------------------------------------------


@pytest.mark.asyncio
async def test_inaccessible_source_on_resolve() -> None:
    gw = FakeTelegramGateway(
        sources={
            "gone": make_source(telegram_id=9, username="gone", accessible=True),
        }
    )
    gw.mark_inaccessible(username="gone", telegram_id=9)
    with pytest.raises(GatewaySourceInaccessible):
        await gw.resolve_public_source(
            PublicSourceRef(schema_version=1, username_or_url="gone")
        )


@pytest.mark.asyncio
async def test_inaccessible_source_on_per_source_search() -> None:
    gw = _gateway()
    gw.mark_inaccessible(telegram_id=55)
    with pytest.raises(GatewaySourceInaccessible):
        await gw.search_source_messages(
            SourceMessageSearchRequest(
                schema_version=1,
                source=SourceRef(schema_version=1, source_id=1, telegram_id=55),
                query="сайт",
                limit=10,
            )
        )


# --- Linked discussion exists / absent / private --------------------------------


@pytest.mark.asyncio
async def test_linked_discussion_exists() -> None:
    gw = _gateway()
    discussion = make_source(
        telegram_id=301, username="chan_chat", source_type="megagroup"
    )
    gw.set_linked_discussion(300, discussion)
    result = await gw.get_linked_discussion(
        SourceRef(schema_version=1, source_id=1, telegram_id=300)
    )
    assert result == discussion


@pytest.mark.asyncio
async def test_linked_discussion_absent() -> None:
    gw = _gateway()
    result = await gw.get_linked_discussion(
        SourceRef(schema_version=1, source_id=1, telegram_id=999)
    )
    assert result is None


@pytest.mark.asyncio
async def test_linked_discussion_private() -> None:
    gw = _gateway()
    private_chat = make_source(
        telegram_id=302, username="private_disc", source_type="megagroup"
    )
    gw.set_linked_discussion(300, private_chat, private=True)
    result = await gw.get_linked_discussion(
        SourceRef(schema_version=1, source_id=1, telegram_id=300)
    )
    assert result is None


# --- Duplicate messages across queries ------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_messages_across_queries() -> None:
    gw = _gateway()
    src = make_source(telegram_id=400, username="dup_chan")
    shared = make_hit(source=src, message_id=42, excerpt="нужен разработчик сайта")
    other = make_hit(source=src, message_id=43, excerpt="ищу бота")
    gw.set_public_post_hits("нужен разработчик", [shared, other])
    gw.set_public_post_hits("разработчик сайта", [shared])
    gw.set_quota(free_slot_available=True, stars_amount=0)

    page_a = await gw.search_public_posts(
        PublicPostSearchRequest(
            schema_version=1, query="нужен разработчик", limit=10
        )
    )
    page_b = await gw.search_public_posts(
        PublicPostSearchRequest(
            schema_version=1, query="разработчик сайта", limit=10
        )
    )
    ids_a = {(h.source.telegram_id, h.telegram_message_id) for h in page_a.hits}
    ids_b = {(h.source.telegram_id, h.telegram_message_id) for h in page_b.hits}
    assert (400, 42) in ids_a
    assert (400, 42) in ids_b
    assert ids_a & ids_b == {(400, 42)}


# --- Cursor stability / empty page ----------------------------------------------


@pytest.mark.asyncio
async def test_search_global_empty_and_cursor_token() -> None:
    gw = _gateway()
    page = await gw.search_global(
        GlobalSearchRequest(
            schema_version=1,
            query="nothing",
            limit=10,
            cursor=SearchCursor(schema_version=1, token="0"),
        )
    )
    assert page.hits == ()
    assert page.next_cursor is None
    assert page.truncated is False


# --- Wave 05: TelegramPeerRef / history / live (COL-023..026) -----------------


@pytest.mark.asyncio
async def test_history_request_requires_peer_and_never_uses_source_id_entity() -> None:
    from telegram_lead_discovery.collector.ports import (
        HistoryRequest,
        TelegramMessageDTO,
        TelegramPeerRef,
    )

    peer = TelegramPeerRef(schema_version=1, telegram_peer_id=501, username_normalized="p")
    with pytest.raises(ValueError):
        TelegramPeerRef(schema_version=1)

    now = datetime.now(UTC)
    gw = FakeTelegramGateway()
    msgs = [
        TelegramMessageDTO(
            schema_version=1,
            source_id=7,
            telegram_message_id=i,
            published_at=now,
            text=f"t{i}",
            telegram_peer_id=501,
        )
        for i in range(1, 4)
    ]
    gw.register_messages_for_peer(501, msgs)
    request = HistoryRequest(
        schema_version=1,
        source_id=7,
        peer=peer,
        limit=10,
    )
    out = [m async for m in gw.iter_history(request)]
    assert len(out) == 3
    assert gw.resolved_entities == [501]
    assert 7 not in gw.resolved_entities


@pytest.mark.asyncio
async def test_fake_history_paginates_with_continuation_cursor() -> None:
    from telegram_lead_discovery.collector.ports import (
        HistoryRequest,
        TelegramMessageDTO,
        TelegramPeerRef,
    )

    now = datetime.now(UTC)
    gw = FakeTelegramGateway()
    gw.set_page_size(2)  # unrelated to history; history uses request.limit
    msgs = [
        TelegramMessageDTO(
            schema_version=1,
            source_id=1,
            telegram_message_id=i,
            published_at=now,
            text=f"m{i}",
            telegram_peer_id=10,
        )
        for i in range(1, 6)
    ]
    gw.register_messages_for_peer(10, msgs)
    peer = TelegramPeerRef(schema_version=1, telegram_peer_id=10)
    page1 = [
        m
        async for m in gw.iter_history(
            HistoryRequest(schema_version=1, source_id=1, peer=peer, limit=2)
        )
    ]
    assert [m.telegram_message_id for m in page1] == [5, 4]  # newest-first
    oldest = min(m.telegram_message_id for m in page1)
    page2 = [
        m
        async for m in gw.iter_history(
            HistoryRequest(
                schema_version=1,
                source_id=1,
                peer=peer,
                limit=2,
                continuation_cursor=str(oldest),
            )
        )
    ]
    assert [m.telegram_message_id for m in page2] == [3, 2]


@pytest.mark.asyncio
async def test_fake_live_updates_queue() -> None:
    from telegram_lead_discovery.collector.ports import (
        TelegramMessageDTO,
        TelegramUpdateDTO,
    )

    gw = FakeTelegramGateway()
    now = datetime.now(UTC)
    msg = TelegramMessageDTO(
        schema_version=1,
        source_id=0,
        telegram_message_id=1,
        published_at=now,
        text="hi",
        telegram_peer_id=99,
    )
    await gw.push_update(
        TelegramUpdateDTO(
            schema_version=1,
            event_type="message_new",
            message=msg,
            observed_at=now,
            telegram_peer_id=99,
        )
    )
    await gw.close_updates()
    updates = [u async for u in gw.iter_updates()]
    assert len(updates) == 1
    assert updates[0].telegram_peer_id == 99
    assert updates[0].message is not None
    assert updates[0].message.telegram_peer_id == 99
