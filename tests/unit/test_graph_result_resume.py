from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from telegram_lead_discovery.collector.adapter.telethon_parts.graph_mixin import (
    _graph_messages_from_history,
)
from telegram_lead_discovery.collector.ports import GraphEdgeDTO, SourceRef
from telegram_lead_discovery.source_discovery.graph_cursor import edge_to_dict
from telegram_lead_discovery.source_discovery.graph_discovery import GraphQueueItem
from telegram_lead_discovery.source_discovery.worker_parts.graph_stages import (
    load_or_fetch_stage,
)


class _NoRepeatGateway:
    async def sample_public_graph(self, request):
        raise AssertionError("saved graph stage must not repeat Telegram request")


@pytest.mark.asyncio
async def test_saved_post_stage_resumes_without_repeat_request() -> None:
    edge = GraphEdgeDTO(
        schema_version=1,
        edge_type="mention",
        seed_telegram_id=100,
        raw_reference="@child",
        normalized_username="child",
        evidence_message_id=11,
    )
    ctx = SimpleNamespace(
        gateway=_NoRepeatGateway(),
        completed_stages={"peer:100": set()},
        stage_results={
            "peer:100": {
                "message_sample_100": {
                    "schema_version": 1,
                    "edges": [edge_to_dict(edge)],
                    "source_telegram_id": 100,
                    "request_ordinal": 17,
                    "posts_persisted": 100,
                }
            }
        },
    )
    node = GraphQueueItem(
        seed_telegram_id=100,
        seed_source_id=1,
        depth=0,
        username="seed",
    )

    edges, completed = await load_or_fetch_stage(ctx, node, "message_sample_100")

    assert completed is False
    assert edges == [edge]


def test_raw_graph_history_keeps_post_fields_without_extra_lookup() -> None:
    published = datetime(2026, 8, 13, 9, 30, tzinfo=UTC)
    raw_message = SimpleNamespace(
        id=44,
        date=published,
        message="Нужен сайт",
        from_id=SimpleNamespace(user_id=501),
        sender=None,
        via_bot_id=None,
        post_author=None,
    )
    result = SimpleNamespace(
        messages=[raw_message],
        users=[SimpleNamespace(id=501, bot=False)],
    )
    source = SourceRef(
        schema_version=1,
        source_id=7,
        telegram_id=100,
        username="client_chat",
    )

    messages = _graph_messages_from_history(result, source, 100)

    assert len(messages) == 1
    message = messages[0]
    assert message.telegram_message_id == 44
    assert message.published_at == published
    assert message.text == "Нужен сайт"
    assert message.author_kind == "user"
    assert message.author_peer_id == 501
    assert message.permalink == "https://t.me/client_chat/44"
