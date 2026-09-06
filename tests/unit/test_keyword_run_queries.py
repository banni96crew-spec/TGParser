"""D-073 / SRC-055 query expansion without Telegram."""

from __future__ import annotations

import pytest

from telegram_lead_discovery.source_discovery.keyword_run_queries import (
    expand_run_queries,
    normalize_seed_refs,
)


def test_global_message_is_groups_only_even_with_many_posts() -> None:
    rows = expand_run_queries(
        run_id=1,
        post_queries=("нужен сайт", "ищу бота"),
        directory_queries=("чат",),
    )
    globals_ = [row for row in rows if row.query_kind == "global_message"]
    assert len(globals_) == 2
    assert {row.scope for row in globals_} == {"groups"}
    assert [row.query_text for row in globals_] == ["нужен сайт", "ищу бота"]
    kinds = [row.query_kind for row in rows]
    assert kinds[0] == "global_message"
    assert "directory" in kinds
    assert kinds[-1] == "public_posts" or "public_posts" in kinds
    assert "operator_seed" not in kinds


def test_operator_seed_rows_follow_posts_and_cap() -> None:
    rows = expand_run_queries(
        run_id=7,
        post_queries=("нужен сайт",),
        directory_queries=(),
        seed_refs=normalize_seed_refs((" @Workk_onchat ", "https://t.me/GetClient")),
    )
    seeds = [row for row in rows if row.query_kind == "operator_seed"]
    assert [row.query_text for row in seeds] == ["@Workk_onchat", "https://t.me/GetClient"]
    assert all(row.scope is None for row in seeds)
    kinds = [row.query_kind for row in rows]
    assert kinds.index("operator_seed") > kinds.index("public_posts")


def test_normalize_seed_refs_rejects_more_than_25() -> None:
    with pytest.raises(ValueError, match="seed_refs_limit_exceeded"):
        normalize_seed_refs([f"seed{i:02d}x" for i in range(26)])


def test_normalize_seed_refs_keeps_invite_and_rejects_invalid() -> None:
    refs = normalize_seed_refs(("https://t.me/+R_KxUQG5hYo5ZjAy", "@poiskfreelance"))
    assert refs[0].startswith("https://t.me/+")
    assert refs[1] == "@poiskfreelance"
    with pytest.raises(ValueError, match="invalid_seed_ref"):
        normalize_seed_refs(("not a telegram ref",))
