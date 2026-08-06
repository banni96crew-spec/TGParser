"""Keyword discovery persisted worker (SRC-019..029, plan §12).

Drives phases B–I for ``job_type=keyword_discovery``. Persists only scouting
evidence / opportunity snapshots — never TelegramMessage, Lead, outbox, or
checkpoint (D-052). FloodWait and transient errors use Job.retry_wait; the
worker never long-sleeps in the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.collector.ports import (
    DirectorySearchRequest,
    GatewayFloodWait,
    GatewayFrozen,
    GatewayInvalidSearchQuery,
    GatewayPermanentError,
    GatewayPremiumRequired,
    GatewaySearchQuotaExhausted,
    GatewaySourceInaccessible,
    GatewayTransientError,
    GatewayUnauthorized,
    GlobalSearchRequest,
    HistoryRequest,
    PublicPostSearchRequest,
    SearchCursor,
    SourceRef,
    SourceSnapshot,
    TelegramGateway,
    TelegramPeerRef,
)
from telegram_lead_discovery.detection.engine import seed_catalog_detect
from telegram_lead_discovery.observability.discovery import (
    log_query_progress,
    log_run_finished,
    note_flood_wait,
    note_quota_skipped,
    note_run_recovered,
    note_session_fatal,
    note_transient_error,
    record_funnel_observability,
    record_qualified_evidence,
    record_query_total,
    record_run_duration_seconds,
    record_run_total,
    record_score,
    record_search_hits,
    record_unique_sources,
    record_verified_sources,
)
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    SEED_DIRECTORY_REPLACEMENT_QUERIES,
    normalize_query,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    JOB_TYPE_KEYWORD_DISCOVERY,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    HISTORY_SCAN_CAP_PER_RUN,
    HISTORY_SCAN_CAP_PER_SOURCE,
    MAX_DEEP_VERIFICATION_SOURCES,
    MAX_EVIDENCE_PER_RUN,
    MAX_NOISE_EVIDENCE_PER_RUN,
    MAX_QUALIFIED_EVIDENCE_PER_RUN,
    QUALITY_WINDOW_DAYS,
    AnnotatedSearchHit,
    DismissedKeywordSourceEntry,
    DismissedKeywordSourceIndex,
    EvidenceRecord,
    OpportunitySnapshotRecord,
    PresentedKeywordSourceEntry,
    PresentedKeywordSourceIndex,
    RegistrySourceEntry,
    SourceRegistryIndex,
    acquire_with_replacement,
    aggregate_search_hits,
    build_opportunity_from_evidence,
    build_preliminary_candidates,
    is_registry_suppressed,
    linked_discussion_opportunity,
    merge_funnel_counters,
    preliminary_rank_key,
    qualify_excerpt_text,
    registry_telegram_ids,
    resolve_dismissed_identity,
    resolve_presented_identity,
    resolve_source_identity,
)
from telegram_lead_discovery.source_discovery.profile_service import version_as_normalized
from telegram_lead_discovery.source_discovery.quality_truth import (
    GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS,
    GATE_MIN_QUALITY_SOURCES,
    HISTORY_PAGE_SIZE,
    ClientRequestIdentity,
    classify_truth_status,
    distinct_client_request_count,
    evaluate_run_gate,
    is_client_request,
    is_within_quality_window,
    pick_next_fair_source,
    quality_window_start,
)
from telegram_lead_discovery.storage.dismissed_suppress import (
    SuppressIdentity,
    peer_canonical_key,
)
from telegram_lead_discovery.storage.jobs import (
    HEARTBEAT_SECONDS,
    LEASE_SECONDS,
    claim_job,
    heartbeat_job,
    recover_stale_jobs,
)
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    DismissedKeywordSource,
    Job,
    KeywordDiscoveryProfileVersion,
    PresentedKeywordSource,
    SourceAlias,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)
from telegram_lead_discovery.storage.presented_suppress import upsert_presented_suppress

GLOBAL_PAGE_SIZE = 50
GLOBAL_MAX_PAGES = 2
DIRECTORY_PEER_LIMIT = 20
DEEP_QUERIES_PER_SOURCE = 5  # legacy; history scan uses one query per source
HISTORY_SCAN_QUERY_TEXT = "history_scan"
TRANSIENT_RETRY_DELAYS_S = (30, 120, 600)
MAX_TRANSIENT_ATTEMPTS = 3
NOISE_EVIDENCE_CAP_PER_SOURCE = 20

# Re-export lease constants so callers/tests bind to the same job-store values.
assert LEASE_SECONDS == 300
assert HEARTBEAT_SECONDS == 60


@dataclass
class WorkerRuntimeConfig:
    GLOBAL_PAGE_SIZE: int = GLOBAL_PAGE_SIZE
    GLOBAL_MAX_PAGES: int = GLOBAL_MAX_PAGES
    DIRECTORY_PEER_LIMIT: int = DIRECTORY_PEER_LIMIT
    DEEP_QUERIES_PER_SOURCE: int = DEEP_QUERIES_PER_SOURCE
    HISTORY_SCAN_QUERY_TEXT: str = HISTORY_SCAN_QUERY_TEXT
    TRANSIENT_RETRY_DELAYS_S: tuple[int, ...] = TRANSIENT_RETRY_DELAYS_S
    MAX_TRANSIENT_ATTEMPTS: int = MAX_TRANSIENT_ATTEMPTS
    NOISE_EVIDENCE_CAP_PER_SOURCE: int = NOISE_EVIDENCE_CAP_PER_SOURCE
    HISTORY_SCAN_CAP_PER_RUN: int = HISTORY_SCAN_CAP_PER_RUN
    HISTORY_SCAN_CAP_PER_SOURCE: int = HISTORY_SCAN_CAP_PER_SOURCE
    MAX_DEEP_VERIFICATION_SOURCES: int = MAX_DEEP_VERIFICATION_SOURCES
    MAX_EVIDENCE_PER_RUN: int = MAX_EVIDENCE_PER_RUN
    MAX_NOISE_EVIDENCE_PER_RUN: int = MAX_NOISE_EVIDENCE_PER_RUN
    MAX_QUALIFIED_EVIDENCE_PER_RUN: int = MAX_QUALIFIED_EVIDENCE_PER_RUN
    QUALITY_WINDOW_DAYS: int = QUALITY_WINDOW_DAYS
    GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS: int = GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS
    GATE_MIN_QUALITY_SOURCES: int = GATE_MIN_QUALITY_SOURCES
    HISTORY_PAGE_SIZE: int = HISTORY_PAGE_SIZE
    HEARTBEAT_SECONDS: int = HEARTBEAT_SECONDS
    LEASE_SECONDS: int = LEASE_SECONDS


RUNTIME_CONFIG = WorkerRuntimeConfig()
