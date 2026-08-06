"""Compatibility facade for persisted keyword and graph discovery workers."""

from __future__ import annotations

from typing import Any

from telegram_lead_discovery.source_discovery.worker_parts.claims import (
    GraphDiscoveryClaimLoop as _GraphDiscoveryClaimLoop,
    KeywordDiscoveryClaimLoop as _KeywordDiscoveryClaimLoop,
    claim_and_process_graph_job as _claim_graph,
    claim_and_process_keyword_job as _claim_keyword,
)
from telegram_lead_discovery.source_discovery.worker_parts.coordinator import (
    process_keyword_discovery_job as _process_keyword,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_worker import (
    process_graph_discovery_job as _process_graph,
)
from telegram_lead_discovery.source_discovery.worker_parts.history_state import _load_history_cursor
from telegram_lead_discovery.source_discovery.worker_parts.query_state import (
    _TERMINAL_VERIFICATION_STATES,
    _finished_verification_sources,
)
from telegram_lead_discovery.source_discovery.worker_parts.registry import (
    _load_dismissed_sources,
)
from telegram_lead_discovery.source_discovery.worker_parts.dependencies import (
    DEEP_QUERIES_PER_SOURCE,
    DIRECTORY_PEER_LIMIT,
    GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS,
    GATE_MIN_QUALITY_SOURCES,
    GLOBAL_MAX_PAGES,
    GLOBAL_PAGE_SIZE,
    HEARTBEAT_SECONDS,
    HISTORY_PAGE_SIZE,
    HISTORY_SCAN_CAP_PER_RUN,
    HISTORY_SCAN_CAP_PER_SOURCE,
    HISTORY_SCAN_QUERY_TEXT,
    LEASE_SECONDS,
    MAX_DEEP_VERIFICATION_SOURCES,
    MAX_EVIDENCE_PER_RUN,
    MAX_NOISE_EVIDENCE_PER_RUN,
    MAX_QUALIFIED_EVIDENCE_PER_RUN,
    MAX_TRANSIENT_ATTEMPTS,
    NOISE_EVIDENCE_CAP_PER_SOURCE,
    QUALITY_WINDOW_DAYS,
    RUNTIME_CONFIG,
    TRANSIENT_RETRY_DELAYS_S,
)

def _sync_runtime_constants() -> None:
    for name in _RUNTIME_CONSTANT_NAMES:
        setattr(RUNTIME_CONFIG, name, globals()[name])


_RUNTIME_CONSTANT_NAMES = (
    "DEEP_QUERIES_PER_SOURCE",
    "DIRECTORY_PEER_LIMIT",
    "GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS",
    "GATE_MIN_QUALITY_SOURCES",
    "GLOBAL_MAX_PAGES",
    "GLOBAL_PAGE_SIZE",
    "HEARTBEAT_SECONDS",
    "HISTORY_PAGE_SIZE",
    "HISTORY_SCAN_CAP_PER_RUN",
    "HISTORY_SCAN_CAP_PER_SOURCE",
    "HISTORY_SCAN_QUERY_TEXT",
    "LEASE_SECONDS",
    "MAX_DEEP_VERIFICATION_SOURCES",
    "MAX_EVIDENCE_PER_RUN",
    "MAX_NOISE_EVIDENCE_PER_RUN",
    "MAX_QUALIFIED_EVIDENCE_PER_RUN",
    "MAX_TRANSIENT_ATTEMPTS",
    "NOISE_EVIDENCE_CAP_PER_SOURCE",
    "QUALITY_WINDOW_DAYS",
    "TRANSIENT_RETRY_DELAYS_S",
)


async def process_keyword_discovery_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_runtime_constants()
    return await _process_keyword(*args, **kwargs)


async def claim_and_process_keyword_job(*args: Any, **kwargs: Any) -> bool:
    _sync_runtime_constants()
    return await _claim_keyword(*args, **kwargs)


async def process_graph_discovery_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
    _sync_runtime_constants()
    return await _process_graph(*args, **kwargs)


async def claim_and_process_graph_job(*args: Any, **kwargs: Any) -> bool:
    _sync_runtime_constants()
    return await _claim_graph(*args, **kwargs)


class KeywordDiscoveryClaimLoop(_KeywordDiscoveryClaimLoop):
    """Compatibility loop that applies facade runtime overrides before work."""

    async def _run(self) -> None:
        _sync_runtime_constants()
        await super()._run()


class GraphDiscoveryClaimLoop(_GraphDiscoveryClaimLoop):
    """Compatibility loop that applies facade runtime overrides before work."""

    async def _run(self) -> None:
        _sync_runtime_constants()
        await super()._run()


__all__ = [
    "GraphDiscoveryClaimLoop",
    "KeywordDiscoveryClaimLoop",
    "claim_and_process_graph_job",
    "claim_and_process_keyword_job",
    "process_graph_discovery_job",
    "process_keyword_discovery_job",
]
