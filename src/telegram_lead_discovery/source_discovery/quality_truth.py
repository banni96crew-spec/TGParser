"""Working-client-search quality truth / gate (SRC-046..SRC-049 / D-068)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

TruthStatus = Literal["quality", "near", "inconclusive", "rejected"]
GateStatus = Literal["pass", "fail", "inconclusive"]
ScanStopReason = Literal[
    "quality_reached",
    "window_reached",
    "source_cap",
    "run_cap",
    "source_exhausted",
    "flood_wait",
    "inaccessible",
    "cancelled",
]

# Owner-approved numerics (D-068).
QUALITY_MIN_DISTINCT_CLIENT_REQUESTS = 7
QUALITY_WINDOW_DAYS = 14
GATE_MIN_QUALITY_SOURCES = 5
GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS = 35
HISTORY_CAP_PER_SOURCE = 1500
HISTORY_CAP_PER_RUN = 7500
HISTORY_PAGE_SIZE = 100
NEAR_MIN_DISTINCT = 1
NEAR_MAX_DISTINCT = QUALITY_MIN_DISTINCT_CLIENT_REQUESTS - 1

CLIENT_CATEGORIES = frozenset(
    {
        "direct_order",
        "contractor_search",
        "recommendation_request",
        "potential_need",
    }
)
CLIENT_SERVICE_PROFILES = frozenset(
    {
        "websites",
        "telegram_bots",
        "integrations_api",
        "automation_parsers",
        "ecommerce",
    }
)

_TERMINAL_STOP_REASONS = frozenset(
    {
        "quality_reached",
        "window_reached",
        "source_cap",
        "run_cap",
        "source_exhausted",
        "inaccessible",
        "cancelled",
    }
)


@dataclass(frozen=True, slots=True)
class ClientRequestIdentity:
    """Distinct client-request identity for quality / global gates."""

    telegram_peer_id: int
    telegram_message_id: int
    normalized_hash: str


@dataclass(frozen=True, slots=True)
class SourceScanProgress:
    scanned_count: int
    distinct_qualified_count: int
    stop_reason: ScanStopReason | None
    offset_message_id: int | None
    window_complete: bool
    hit_source_cap: bool
    hit_run_cap: bool


@dataclass(frozen=True, slots=True)
class RunGateResult:
    gate_status: GateStatus
    quality_sources: int
    near_sources: int
    inconclusive_sources: int
    rejected_sources: int
    globally_distinct_client_requests: int


def quality_window_start(now: datetime, *, days: int = QUALITY_WINDOW_DAYS) -> datetime:
    now_utc = _ensure_utc(now)
    return now_utc - timedelta(days=days)


def is_within_quality_window(
    published_at: datetime,
    *,
    now: datetime,
    days: int = QUALITY_WINDOW_DAYS,
) -> bool:
    return _ensure_utc(published_at) >= quality_window_start(now, days=days)


def is_client_request(
    *,
    category: str,
    service_profiles: Sequence[str],
    hard_exclusion: bool,
) -> bool:
    if hard_exclusion:
        return False
    if category not in CLIENT_CATEGORIES:
        return False
    return any(s in CLIENT_SERVICE_PROFILES for s in service_profiles)


def distinct_client_request_count(
    identities: Iterable[ClientRequestIdentity],
) -> int:
    """Count globally distinct requests: message identity ∪ normalized_hash."""
    seen_ids: set[tuple[int, int]] = set()
    seen_hashes: set[str] = set()
    count = 0
    for item in identities:
        id_key = (item.telegram_peer_id, item.telegram_message_id)
        if id_key in seen_ids or item.normalized_hash in seen_hashes:
            continue
        seen_ids.add(id_key)
        if item.normalized_hash:
            seen_hashes.add(item.normalized_hash)
        count += 1
    return count


def classify_truth_status(
    *,
    distinct_qualified_in_window: int,
    window_complete: bool,
    hit_source_cap: bool,
    hit_run_cap: bool,
) -> TruthStatus:
    """Map scan outcome to operator-facing truth bucket (SRC-046).

    Soft caps MUST yield ``inconclusive`` (недоказанный), never silent reject.
    Soft-cap interruption overrides ``near`` when quality is not reached.
    Rejected only when a completed 14-day scan proves 0 distinct client requests.
    """
    if distinct_qualified_in_window >= QUALITY_MIN_DISTINCT_CLIENT_REQUESTS:
        return "quality"
    if hit_source_cap or hit_run_cap:
        return "inconclusive"
    if NEAR_MIN_DISTINCT <= distinct_qualified_in_window <= NEAR_MAX_DISTINCT:
        return "near"
    if window_complete and distinct_qualified_in_window == 0:
        return "rejected"
    if not window_complete:
        return "inconclusive"
    return "inconclusive"


def evaluate_run_gate(
    *,
    truth_statuses: Sequence[TruthStatus],
    globally_distinct_client_requests: int,
    hit_run_cap: bool = False,
    pool_exhausted: bool = False,
) -> RunGateResult:
    """Working-run gate (SRC-047).

    PASS only real ≥5 quality × ≥35 distinct.
    Run soft-cap before pool exhaustion without PASS ⇒ INCONCLUSIVE (not FAIL).
    Pool exhausted below target without that cap path ⇒ FAIL.
    """
    quality_sources = sum(1 for s in truth_statuses if s == "quality")
    near_sources = sum(1 for s in truth_statuses if s == "near")
    inconclusive_sources = sum(1 for s in truth_statuses if s == "inconclusive")
    rejected_sources = sum(1 for s in truth_statuses if s == "rejected")
    if (
        quality_sources >= GATE_MIN_QUALITY_SOURCES
        and globally_distinct_client_requests >= GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS
    ):
        gate_status: GateStatus = "pass"
    elif hit_run_cap and not pool_exhausted:
        gate_status = "inconclusive"
    else:
        gate_status = "fail"
    return RunGateResult(
        gate_status=gate_status,
        quality_sources=quality_sources,
        near_sources=near_sources,
        inconclusive_sources=inconclusive_sources,
        rejected_sources=rejected_sources,
        globally_distinct_client_requests=globally_distinct_client_requests,
    )


def pick_next_fair_source(
    *,
    pool_telegram_ids: Sequence[int],
    scanned_by_source: Mapping[int, int],
    finished_sources: set[int],
    source_cap: int = HISTORY_CAP_PER_SOURCE,
) -> int | None:
    """Waterfill: next unfinished source with the fewest scanned messages (pool order tie-break).

    Technical scheduling only — does not change owner caps 1500/source or 7500/run.
    Ensures later candidates are probed before an early weak source monopolizes 1500.
    """
    best: tuple[int, int] | None = None  # (scanned, pool_index)
    best_tid: int | None = None
    for idx, tid in enumerate(pool_telegram_ids):
        if tid in finished_sources:
            continue
        scanned = int(scanned_by_source.get(tid, 0))
        if scanned >= source_cap:
            continue
        key = (scanned, idx)
        if best is None or key < best:
            best = key
            best_tid = tid
    return best_tid


def is_terminal_stop_reason(stop_reason: str | None) -> bool:
    return stop_reason in _TERMINAL_STOP_REASONS


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "CLIENT_CATEGORIES",
    "CLIENT_SERVICE_PROFILES",
    "ClientRequestIdentity",
    "GATE_MIN_GLOBAL_DISTINCT_CLIENT_REQUESTS",
    "GATE_MIN_QUALITY_SOURCES",
    "GateStatus",
    "HISTORY_CAP_PER_RUN",
    "HISTORY_CAP_PER_SOURCE",
    "HISTORY_PAGE_SIZE",
    "NEAR_MAX_DISTINCT",
    "NEAR_MIN_DISTINCT",
    "QUALITY_MIN_DISTINCT_CLIENT_REQUESTS",
    "QUALITY_WINDOW_DAYS",
    "RunGateResult",
    "ScanStopReason",
    "SourceScanProgress",
    "TruthStatus",
    "classify_truth_status",
    "distinct_client_request_count",
    "evaluate_run_gate",
    "is_client_request",
    "is_terminal_stop_reason",
    "is_within_quality_window",
    "pick_next_fair_source",
    "quality_window_start",
]
