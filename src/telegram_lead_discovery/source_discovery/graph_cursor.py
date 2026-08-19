"""Graph cursor v2 serialization helpers."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.collector.ports import GraphEdgeDTO, SourceSnapshot
from telegram_lead_discovery.source_discovery.graph_policy import GraphQueueItem


def node_key(node: GraphQueueItem) -> str:
    if node.seed_telegram_id:
        return f"peer:{node.seed_telegram_id}"
    return f"username:{(node.username or '').casefold()}"


def node_to_dict(node: GraphQueueItem) -> dict[str, Any]:
    return {
        "seed_telegram_id": node.seed_telegram_id,
        "seed_source_id": node.seed_source_id,
        "depth": node.depth,
        "username": node.username,
        "access_hash": node.access_hash,
    }


def node_from_dict(value: dict[str, Any]) -> GraphQueueItem:
    return GraphQueueItem(
        seed_telegram_id=int(value.get("seed_telegram_id") or 0),
        seed_source_id=value.get("seed_source_id"),
        depth=int(value.get("depth") or 0),
        username=value.get("username"),
        access_hash=value.get("access_hash"),
    )


def snapshot_to_dict(snapshot: SourceSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "telegram_id": snapshot.telegram_id,
        "username": snapshot.username,
        "title": snapshot.title,
        "source_type": snapshot.source_type,
        "public_url": snapshot.public_url,
        "accessible": snapshot.accessible,
        "access_hash": snapshot.access_hash,
    }


def snapshot_from_dict(value: dict[str, Any]) -> SourceSnapshot:
    return SourceSnapshot(
        schema_version=int(value.get("schema_version") or 1),
        telegram_id=int(value["telegram_id"]),
        username=str(value.get("username") or ""),
        title=str(value.get("title") or ""),
        source_type=value.get("source_type") or "channel",
        public_url=value.get("public_url"),
        accessible=bool(value.get("accessible", True)),
        access_hash=value.get("access_hash"),
    )


def edge_to_dict(edge: GraphEdgeDTO) -> dict[str, Any]:
    return {
        "schema_version": edge.schema_version,
        "edge_type": edge.edge_type,
        "seed_telegram_id": edge.seed_telegram_id,
        "raw_reference": edge.raw_reference,
        "normalized_username": edge.normalized_username,
        "target": snapshot_to_dict(edge.target) if edge.target is not None else None,
        "evidence_message_id": edge.evidence_message_id,
    }


def edge_from_dict(value: dict[str, Any]) -> GraphEdgeDTO:
    target = value.get("target")
    return GraphEdgeDTO(
        schema_version=int(value.get("schema_version") or 1),
        edge_type=value["edge_type"],
        seed_telegram_id=int(value["seed_telegram_id"]),
        raw_reference=str(value.get("raw_reference") or ""),
        normalized_username=value.get("normalized_username"),
        target=snapshot_from_dict(target) if isinstance(target, dict) else None,
        evidence_message_id=value.get("evidence_message_id"),
    )


__all__ = [
    "edge_from_dict",
    "edge_to_dict",
    "node_from_dict",
    "node_key",
    "node_to_dict",
    "snapshot_from_dict",
    "snapshot_to_dict",
]
