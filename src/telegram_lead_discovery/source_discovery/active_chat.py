"""Deterministic ActiveClientChat v1 counters, truth and source score."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

TruthStatus = Literal["quality", "near", "inconclusive", "rejected"]
OpportunityBand = Literal["promising", "review", "weak"]
TerminalStopReason = Literal[
    "quality_reached",
    "window_complete",
    "history_exhausted",
    "source_cap",
    "run_cap",
    "inaccessible",
    "cancelled",
]

ACTIVITY_WINDOW_DAYS = 14
DEMAND_WINDOW_DAYS = 30
FRESHNESS_WINDOW_DAYS = 7
MIN_ACTIVITY_MESSAGES = 100
MIN_ACTIVITY_DAYS = 10
MIN_ACTIVITY_AUTHORS = 20
MIN_CLIENT_REQUESTS = 3
MIN_CLIENT_AUTHORS = 3
COUNTABLE_CATEGORIES = frozenset({"direct_order", "contractor_search", "recommendation_request"})
SUPPORTED_SERVICES = frozenset(
    {"websites", "telegram_bots", "integrations_api", "automation_parsers", "ecommerce"}
)
INCOMPLETE_REASONS = frozenset({"source_cap", "run_cap", "inaccessible", "cancelled"})
COMPLETE_REASONS = frozenset({"window_complete", "history_exhausted"})


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def source_scoped_author_key(source_telegram_id: int, author_peer_id: int) -> str:
    payload = f"active-chat-v1:{int(source_telegram_id)}:{int(author_peer_id)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_countable_client_request(
    *,
    category: str,
    service_profiles: Sequence[str],
    hard_exclusion: bool,
    author_kind: str,
    required_service_profiles: Sequence[str] = (),
) -> bool:
    services = set(service_profiles)
    return (
        author_kind == "user"
        and not hard_exclusion
        and category in COUNTABLE_CATEGORIES
        and bool(services & SUPPORTED_SERVICES)
        and all(required in services for required in required_service_profiles)
    )


@dataclass(frozen=True, slots=True)
class ActiveChatMessage:
    telegram_message_id: int
    published_at: datetime
    normalized_hash: str
    author_kind: str
    author_key: str | None
    detection_category: str
    service_profiles: tuple[str, ...]
    hard_exclusion: bool
    profile_exclusion_reason: str | None = None


@dataclass(slots=True)
class ActiveChatAccumulator:
    reference_at: datetime
    seen_message_ids: set[int] = field(default_factory=set)
    activity_message_ids: set[int] = field(default_factory=set)
    activity_dates: set[str] = field(default_factory=set)
    activity_author_keys: set[str] = field(default_factory=set)
    request_message_ids: set[int] = field(default_factory=set)
    request_hashes: set[str] = field(default_factory=set)
    request_author_keys: set[str] = field(default_factory=set)
    hard_excluded_message_ids: set[int] = field(default_factory=set)
    profile_excluded_message_ids: set[int] = field(default_factory=set)
    matched_service_profiles: set[str] = field(default_factory=set)
    unknown_hashes: set[str] = field(default_factory=set)
    latest_client_request_at: datetime | None = None

    def consume(
        self,
        message: ActiveChatMessage,
        *,
        required_service_profiles: Sequence[str] = (),
    ) -> bool:
        """Consume once by Telegram identity; return whether request is countable and novel."""
        message_id = int(message.telegram_message_id)
        published = ensure_utc(message.published_at)
        reference = ensure_utc(self.reference_at)
        if message_id in self.seen_message_ids or published > reference:
            return False
        self.seen_message_ids.add(message_id)
        if not message.normalized_hash:
            return False
        demand_start = reference - timedelta(days=DEMAND_WINDOW_DAYS)
        if published < demand_start:
            return False
        activity_start = reference - timedelta(days=ACTIVITY_WINDOW_DAYS)
        if published >= activity_start:
            self.activity_message_ids.add(message_id)
            self.activity_dates.add(published.date().isoformat())
            if message.author_kind == "user" and message.author_key:
                self.activity_author_keys.add(message.author_key)
        if message.hard_exclusion:
            self.hard_excluded_message_ids.add(message_id)
        if message.profile_exclusion_reason:
            self.profile_excluded_message_ids.add(message_id)
        if message.author_kind == "unknown" and message.normalized_hash not in self.unknown_hashes:
            self.unknown_hashes.add(message.normalized_hash)

        potential_request = (
            message.author_kind == "user"
            and not message.hard_exclusion
            and message.detection_category in COUNTABLE_CATEGORIES
        )
        if potential_request:
            self.matched_service_profiles.update(set(message.service_profiles) & SUPPORTED_SERVICES)
        countable = is_countable_client_request(
            category=message.detection_category,
            service_profiles=message.service_profiles,
            hard_exclusion=message.hard_exclusion,
            author_kind=message.author_kind,
            required_service_profiles=required_service_profiles,
        )
        if not countable or not message.author_key:
            return False
        if message_id in self.request_message_ids or message.normalized_hash in self.request_hashes:
            return False
        self.request_message_ids.add(message_id)
        self.request_hashes.add(message.normalized_hash)
        self.request_author_keys.add(message.author_key)
        if self.latest_client_request_at is None or published > self.latest_client_request_at:
            self.latest_client_request_at = published
        return True

    def counters(self) -> ActiveChatCounters:
        return ActiveChatCounters(
            activity_message_count=len(self.activity_message_ids),
            activity_active_day_count=len(self.activity_dates),
            activity_distinct_author_count=len(self.activity_author_keys),
            client_request_count=len(self.request_message_ids),
            client_request_author_count=len(self.request_author_keys),
            hard_excluded_count=len(self.hard_excluded_message_ids),
            unknown_author_message_count=len(self.unknown_hashes),
            latest_client_request_at=self.latest_client_request_at,
            profile_excluded_count=len(self.profile_excluded_message_ids),
            matched_service_profiles=tuple(sorted(self.matched_service_profiles)),
        )

    def to_cursor(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "reference_at": ensure_utc(self.reference_at).isoformat(),
            "seen_message_ids": sorted(self.seen_message_ids),
            "activity_message_ids": sorted(self.activity_message_ids),
            "activity_dates": sorted(self.activity_dates),
            "activity_author_keys": sorted(self.activity_author_keys),
            "request_message_ids": sorted(self.request_message_ids),
            "request_hashes": sorted(self.request_hashes),
            "request_author_keys": sorted(self.request_author_keys),
            "hard_excluded_message_ids": sorted(self.hard_excluded_message_ids),
            "profile_excluded_message_ids": sorted(self.profile_excluded_message_ids),
            "matched_service_profiles": sorted(self.matched_service_profiles),
            "unknown_hashes": sorted(self.unknown_hashes),
            "latest_client_request_at": (
                ensure_utc(self.latest_client_request_at).isoformat()
                if self.latest_client_request_at
                else None
            ),
        }

    @classmethod
    def from_cursor(cls, payload: dict[str, object]) -> ActiveChatAccumulator:
        if int(payload.get("schema_version", 0)) != 2:
            raise ValueError("active_chat_cursor_version")
        latest_raw = payload.get("latest_client_request_at")
        result = cls(
            reference_at=datetime.fromisoformat(str(payload["reference_at"])),
            latest_client_request_at=(
                datetime.fromisoformat(str(latest_raw)) if latest_raw else None
            ),
        )
        for name in (
            "seen_message_ids",
            "activity_message_ids",
            "request_message_ids",
            "hard_excluded_message_ids",
            "profile_excluded_message_ids",
        ):
            setattr(result, name, {int(value) for value in payload.get(name, [])})
        for name in (
            "activity_dates",
            "activity_author_keys",
            "request_hashes",
            "request_author_keys",
            "unknown_hashes",
            "matched_service_profiles",
        ):
            setattr(result, name, {str(value) for value in payload.get(name, [])})
        return result

    def assert_reference_at(self, expected: datetime) -> None:
        """Reject a resumed cursor if its immutable run reference changed."""
        if ensure_utc(self.reference_at) != ensure_utc(expected):
            raise ValueError("active_chat_cursor_reference_mismatch")


@dataclass(frozen=True, slots=True)
class ActiveChatCounters:
    activity_message_count: int
    activity_active_day_count: int
    activity_distinct_author_count: int
    client_request_count: int
    client_request_author_count: int
    hard_excluded_count: int
    unknown_author_message_count: int
    latest_client_request_at: datetime | None
    profile_excluded_count: int = 0
    matched_service_profiles: tuple[str, ...] = ()


from telegram_lead_discovery.source_discovery.active_chat_evaluation import (  # noqa: E402,F401
    ActiveChatEvaluation,
    active_chat_thresholds,
    counters_dict,
    evaluate_active_client_chat,
)
