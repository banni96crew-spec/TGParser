"""Pure extraction and filtering of public graph edges."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import regex

from telegram_lead_discovery.collector.ports import GraphEdgeDTO, GraphEdgeType

ALLOWED_GRAPH_EDGE_TYPES: frozenset[GraphEdgeType] = frozenset(
    {
        "recommendation",
        "public_link",
        "mention",
        "forward_origin",
        "linked_discussion",
    }
)

_MENTION_RE = regex.compile(r"(?<![a-zA-Z0-9_])@([a-zA-Z0-9_]{5,32})\b")
_TME_RE = regex.compile(
    r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32})(?:/[0-9]+)?(?:\?[^\s]*)?",
    flags=regex.IGNORECASE,
)
_PRIVATE_TME_PREFIXES = frozenset(
    {"joinchat", "addstickers", "share", "proxy", "socks", "c", "s"}
)
_REGEX_TIMEOUT = 0.05


def is_private_invite_ref(raw: str) -> bool:
    text = raw.strip().casefold()
    return (
        "t.me/+" in text
        or "t.me/joinchat/" in text
        or text.startswith("+")
        or text.startswith("joinchat/")
    )


def extract_public_usernames_from_text(
    text: str,
) -> tuple[tuple[str, GraphEdgeType], ...]:
    if not text:
        return ()
    ordered: list[tuple[str, GraphEdgeType]] = []
    seen: set[str] = set()
    try:
        for match in _TME_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token in _PRIVATE_TME_PREFIXES or token.startswith("+"):
                continue
            if token not in seen:
                seen.add(token)
                ordered.append((token, "public_link"))
        for match in _MENTION_RE.finditer(text, timeout=_REGEX_TIMEOUT):
            token = match.group(1).lower()
            if token not in seen:
                seen.add(token)
                ordered.append((token, "mention"))
    except TimeoutError:
        return tuple(ordered)
    return tuple(ordered)


def truncate_outgoing_edges(
    edges: Sequence[GraphEdgeDTO], *, limit: int = 25
) -> tuple[GraphEdgeDTO, ...]:
    if limit < 0:
        return ()
    return tuple(edges[:limit])


def filter_allowed_public_edges(
    edges: Iterable[GraphEdgeDTO],
) -> tuple[GraphEdgeDTO, ...]:
    kept: list[GraphEdgeDTO] = []
    for edge in edges:
        if edge.edge_type not in ALLOWED_GRAPH_EDGE_TYPES:
            continue
        if is_private_invite_ref(edge.raw_reference):
            continue
        target = edge.target
        if target is not None and (
            not target.accessible
            or not target.username
            or target.source_type not in {"channel", "megagroup", "group"}
        ):
            continue
        kept.append(edge)
    return tuple(kept)


__all__ = [
    "ALLOWED_GRAPH_EDGE_TYPES",
    "extract_public_usernames_from_text",
    "filter_allowed_public_edges",
    "is_private_invite_ref",
    "truncate_outgoing_edges",
]
