"""Expand a keyword run into DiscoveryRunQuery rows (D-073 / SRC-055)."""

from __future__ import annotations

from collections.abc import Sequence

from telegram_lead_discovery.source_discovery.graph_edges import is_private_invite_ref
from telegram_lead_discovery.source_discovery.normalization import (
    InvalidUsernameError,
    normalize_username,
)
from telegram_lead_discovery.storage.models import DiscoveryRunQuery

MAX_OPERATOR_SEED_REFS = 25


def normalize_seed_refs(raw: Sequence[str] | None) -> tuple[str, ...]:
    refs: list[str] = []
    for item in raw or ():
        text = str(item).strip()
        if not text:
            continue
        if is_private_invite_ref(text):
            refs.append(text)
            continue
        try:
            normalize_username(text)
        except InvalidUsernameError as exc:
            raise ValueError("invalid_seed_ref") from exc
        refs.append(text)
    if len(refs) > MAX_OPERATOR_SEED_REFS:
        raise ValueError("seed_refs_limit_exceeded")
    return tuple(refs)


def expand_run_queries(
    *,
    run_id: int,
    post_queries: tuple[str, ...],
    directory_queries: tuple[str, ...],
    seed_refs: tuple[str, ...] = (),
) -> list[DiscoveryRunQuery]:
    """Global SEARCH is groups-only. Posts remain. operator_seed after posts."""
    rows: list[DiscoveryRunQuery] = []
    ordinal = 0
    for query_text in post_queries:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="global_message",
                query_text=query_text,
                scope="groups",
                state="queued",
            )
        )
    for query_text in directory_queries:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="directory",
                query_text=query_text,
                scope=None,
                state="queued",
            )
        )
    for query_text in post_queries:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="public_posts",
                query_text=query_text,
                scope=None,
                state="queued",
            )
        )
    for ref in seed_refs:
        ordinal += 1
        rows.append(
            DiscoveryRunQuery(
                run_id=run_id,
                ordinal=ordinal,
                query_kind="operator_seed",
                query_text=ref,
                scope=None,
                state="queued",
            )
        )
    return rows
