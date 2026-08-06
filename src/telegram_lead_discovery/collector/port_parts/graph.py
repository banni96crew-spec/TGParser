from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from telegram_lead_discovery.collector.port_parts.sources import SourceRef, SourceSnapshot


GraphEdgeType = Literal[
    "recommendation",
    "public_link",
    "mention",
    "forward_origin",
    "linked_discussion",
]


@dataclass(frozen=True, slots=True)
class GraphEdgeDTO:
    """Public-only graph edge discovered from a seed (SRC-042 / SRC-003)."""

    schema_version: int
    edge_type: GraphEdgeType
    seed_telegram_id: int
    raw_reference: str
    normalized_username: str | None = None
    target: SourceSnapshot | None = None
    evidence_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class GraphSampleRequest:
    """Bounded message sample for public_link / mention / forward_origin edges."""

    schema_version: int
    source: SourceRef
    message_limit: int = 50
