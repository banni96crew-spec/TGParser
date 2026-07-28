"""Identity resolution and suppress indexes for source discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from telegram_lead_discovery.source_discovery.normalization import normalize_username

PRESENTATION_COOLDOWN = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class RegistrySourceEntry:
    """Minimal registry view for SRC-022 identity resolution."""

    source_id: int
    telegram_id: int | None
    username_normalized: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceRegistryIndex:
    """Lookup indexes for identity order telegram_id → username → alias."""

    by_telegram_id: Mapping[int, RegistrySourceEntry] = field(default_factory=dict)
    by_username: Mapping[str, RegistrySourceEntry] = field(default_factory=dict)
    by_alias: Mapping[str, RegistrySourceEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(cls, entries: Sequence[RegistrySourceEntry]) -> SourceRegistryIndex:
        by_tid: dict[int, RegistrySourceEntry] = {}
        by_user: dict[str, RegistrySourceEntry] = {}
        by_alias: dict[str, RegistrySourceEntry] = {}
        for entry in entries:
            if entry.telegram_id is not None:
                by_tid[entry.telegram_id] = entry
            if entry.username_normalized:
                by_user[entry.username_normalized] = entry
            for alias in entry.aliases:
                by_alias[alias] = entry
        return cls(by_telegram_id=by_tid, by_username=by_user, by_alias=by_alias)


@dataclass(frozen=True, slots=True)
class DismissedKeywordSourceEntry:
    """Durable suppress row for future keyword runs (SRC-032)."""

    telegram_id: int
    username_normalized: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DismissedKeywordSourceIndex:
    """Lookup indexes for dismissed suppress identity matching."""

    by_telegram_id: Mapping[int, DismissedKeywordSourceEntry] = field(default_factory=dict)
    by_username: Mapping[str, DismissedKeywordSourceEntry] = field(default_factory=dict)
    by_alias: Mapping[str, DismissedKeywordSourceEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(
        cls, entries: Sequence[DismissedKeywordSourceEntry]
    ) -> DismissedKeywordSourceIndex:
        by_tid: dict[int, DismissedKeywordSourceEntry] = {}
        by_user: dict[str, DismissedKeywordSourceEntry] = {}
        by_alias: dict[str, DismissedKeywordSourceEntry] = {}
        for entry in entries:
            by_tid[entry.telegram_id] = entry
            if entry.username_normalized:
                by_user[entry.username_normalized] = entry
            for alias in entry.aliases:
                by_alias[alias] = entry
        return cls(by_telegram_id=by_tid, by_username=by_user, by_alias=by_alias)


@dataclass(frozen=True, slots=True)
class ResolvedSourceIdentity:
    """Canonical source identity after SRC-022 resolution."""

    canonical_telegram_id: int
    registry_source_id: int | None
    username_normalized: str | None
    matched_via: Literal[
        "telegram_id",
        "registry_telegram_id",
        "username",
        "alias",
        "username_fallback",
    ]


@dataclass(frozen=True, slots=True)
class DismissedIdentityMatch:
    canonical_telegram_id: int
    username_normalized: str | None
    matched_via: Literal["dismissed_telegram_id", "username", "alias"]


def registry_telegram_ids(registry: SourceRegistryIndex) -> frozenset[int]:
    """All telegram_id values currently present in the Source Registry index."""
    return frozenset(registry.by_telegram_id.keys())


def dismissed_telegram_ids(index: DismissedKeywordSourceIndex) -> frozenset[int]:
    """All telegram_id values currently suppressed by past dismiss actions."""
    return frozenset(index.by_telegram_id.keys())


@dataclass(frozen=True, slots=True)
class PresentedKeywordSourceEntry:
    """Durable already-shown suppress row (SRC-041 / D-069)."""

    telegram_id: int
    username_normalized: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresentedKeywordSourceIndex:
    """Lookup indexes for durable presented-source suppress."""

    by_telegram_id: Mapping[int, PresentedKeywordSourceEntry] = field(default_factory=dict)
    by_username: Mapping[str, PresentedKeywordSourceEntry] = field(default_factory=dict)
    by_alias: Mapping[str, PresentedKeywordSourceEntry] = field(default_factory=dict)

    @classmethod
    def from_entries(
        cls, entries: Sequence[PresentedKeywordSourceEntry]
    ) -> PresentedKeywordSourceIndex:
        by_tid: dict[int, PresentedKeywordSourceEntry] = {}
        by_user: dict[str, PresentedKeywordSourceEntry] = {}
        by_alias: dict[str, PresentedKeywordSourceEntry] = {}
        for entry in entries:
            by_tid[entry.telegram_id] = entry
            if entry.username_normalized:
                by_user[entry.username_normalized] = entry
            for alias in entry.aliases:
                by_alias[alias] = entry
        return cls(by_telegram_id=by_tid, by_username=by_user, by_alias=by_alias)

    def contains_telegram_id(self, telegram_id: int) -> bool:
        return telegram_id in self.by_telegram_id


@dataclass(frozen=True, slots=True)
class PresentedIdentityMatch:
    canonical_telegram_id: int
    username_normalized: str | None
    matched_via: Literal["presented_telegram_id", "username", "alias"]


def presented_telegram_ids(index: PresentedKeywordSourceIndex) -> frozenset[int]:
    return frozenset(index.by_telegram_id.keys())


def resolve_presented_identity(
    *,
    telegram_id: int,
    username: str | None,
    presented: PresentedKeywordSourceIndex | None = None,
) -> PresentedIdentityMatch | None:
    """Resolve whether a source matches the durable presented suppress set."""
    if presented is None:
        return None
    username_normalized: str | None = None
    if username:
        try:
            username_normalized = normalize_username(username)
        except ValueError:
            username_normalized = username.strip().lstrip("@").lower() or None
    by_tid = presented.by_telegram_id.get(telegram_id)
    if by_tid is not None:
        return PresentedIdentityMatch(
            canonical_telegram_id=by_tid.telegram_id,
            username_normalized=username_normalized or by_tid.username_normalized,
            matched_via="presented_telegram_id",
        )
    if username_normalized:
        by_user = presented.by_username.get(username_normalized)
        if by_user is not None:
            return PresentedIdentityMatch(
                canonical_telegram_id=by_user.telegram_id,
                username_normalized=username_normalized,
                matched_via="username",
            )
        by_alias = presented.by_alias.get(username_normalized)
        if by_alias is not None:
            return PresentedIdentityMatch(
                canonical_telegram_id=by_alias.telegram_id,
                username_normalized=username_normalized,
                matched_via="alias",
            )
    return None


def is_registry_suppressed(
    identity: ResolvedSourceIdentity,
    *,
    registry: SourceRegistryIndex | None = None,
) -> bool:
    """SRC-031 / D-059: true when identity already resolves to a registry source."""
    if identity.registry_source_id is not None:
        return True
    if registry is None:
        return False
    return identity.canonical_telegram_id in registry.by_telegram_id


def resolve_dismissed_identity(
    *,
    telegram_id: int,
    username: str | None,
    dismissed: DismissedKeywordSourceIndex | None = None,
) -> DismissedIdentityMatch | None:
    """Resolve whether a source matches the durable dismissed suppress set."""
    if dismissed is None:
        return None
    username_normalized: str | None = None
    if username:
        try:
            username_normalized = normalize_username(username)
        except ValueError:
            username_normalized = username.strip().lstrip("@").lower() or None

    by_tid = dismissed.by_telegram_id.get(telegram_id)
    if by_tid is not None:
        return DismissedIdentityMatch(
            canonical_telegram_id=by_tid.telegram_id,
            username_normalized=username_normalized or by_tid.username_normalized,
            matched_via="dismissed_telegram_id",
        )
    if username_normalized:
        by_user = dismissed.by_username.get(username_normalized)
        if by_user is not None:
            return DismissedIdentityMatch(
                canonical_telegram_id=by_user.telegram_id,
                username_normalized=username_normalized,
                matched_via="username",
            )
        by_alias = dismissed.by_alias.get(username_normalized)
        if by_alias is not None:
            return DismissedIdentityMatch(
                canonical_telegram_id=by_alias.telegram_id,
                username_normalized=username_normalized,
                matched_via="alias",
            )
    return None


def resolve_source_identity(
    *,
    telegram_id: int,
    username: str | None,
    registry: SourceRegistryIndex | None = None,
) -> ResolvedSourceIdentity:
    """Apply SRC-022 identity order and return canonical telegram id."""
    username_normalized: str | None = None
    if username:
        try:
            username_normalized = normalize_username(username)
        except ValueError:
            username_normalized = username.strip().lstrip("@").lower() or None

    if registry is not None:
        by_tid = registry.by_telegram_id.get(telegram_id)
        if by_tid is not None:
            return ResolvedSourceIdentity(
                canonical_telegram_id=telegram_id,
                registry_source_id=by_tid.source_id,
                username_normalized=username_normalized or by_tid.username_normalized,
                matched_via="registry_telegram_id",
            )

        if username_normalized:
            by_user = registry.by_username.get(username_normalized)
            if by_user is not None:
                canon = by_user.telegram_id if by_user.telegram_id is not None else telegram_id
                return ResolvedSourceIdentity(
                    canonical_telegram_id=canon,
                    registry_source_id=by_user.source_id,
                    username_normalized=username_normalized,
                    matched_via="username",
                )
            by_alias = registry.by_alias.get(username_normalized)
            if by_alias is not None:
                canon = by_alias.telegram_id if by_alias.telegram_id is not None else telegram_id
                return ResolvedSourceIdentity(
                    canonical_telegram_id=canon,
                    registry_source_id=by_alias.source_id,
                    username_normalized=username_normalized,
                    matched_via="alias",
                )

    if username_normalized:
        return ResolvedSourceIdentity(
            canonical_telegram_id=telegram_id,
            registry_source_id=None,
            username_normalized=username_normalized,
            matched_via="username_fallback",
        )
    return ResolvedSourceIdentity(
        canonical_telegram_id=telegram_id,
        registry_source_id=None,
        username_normalized=None,
        matched_via="telegram_id",
    )


@dataclass(frozen=True, slots=True)
class PresentationCooldownIndex:
    """Deprecated 24h helper — durable presented ledger (SRC-041 / D-069) is authoritative.

    Kept for test compatibility: ``is_cooled_down`` is True iff peer is in
    ``presented_at_by_id`` (treated as permanently presented for suppress checks).
    """

    presented_at_by_id: Mapping[int, datetime] = field(default_factory=dict)

    @classmethod
    def from_entries(
        cls, entries: Sequence[tuple[int, datetime]]
    ) -> PresentationCooldownIndex:
        mapping: dict[int, datetime] = {}
        for telegram_id, presented_at in entries:
            mapping[telegram_id] = _ensure_utc(presented_at)
        return cls(presented_at_by_id=mapping)

    def is_cooled_down(
        self,
        telegram_id: int,
        *,
        now: datetime,
        window: timedelta = PRESENTATION_COOLDOWN,
    ) -> bool:
        _ = now, window
        return telegram_id in self.presented_at_by_id


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)



__all__ = [
    "DismissedIdentityMatch",
    "DismissedKeywordSourceEntry",
    "DismissedKeywordSourceIndex",
    "PRESENTATION_COOLDOWN",
    "PresentationCooldownIndex",
    "PresentedIdentityMatch",
    "PresentedKeywordSourceEntry",
    "PresentedKeywordSourceIndex",
    "RegistrySourceEntry",
    "ResolvedSourceIdentity",
    "SourceRegistryIndex",
    "dismissed_telegram_ids",
    "is_registry_suppressed",
    "presented_telegram_ids",
    "registry_telegram_ids",
    "resolve_dismissed_identity",
    "resolve_presented_identity",
    "resolve_source_identity",
]

