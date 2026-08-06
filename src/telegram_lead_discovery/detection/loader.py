"""Runtime rule catalog loader keyed by checksum (DET-016 / D-065)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.detection.catalog import SeedRule
from telegram_lead_discovery.detection.catalog_codec import catalog_checksum
from telegram_lead_discovery.detection.errors import RuleSetInvalidError
from telegram_lead_discovery.storage.models import MonitoringRule, RuleSetVersion


@dataclass(frozen=True, slots=True)
class LoadedRuleCatalog:
    rule_set_version_id: int
    checksum: str
    rules: tuple[SeedRule, ...]
    hot_min: int
    warm_min: int
    cold_min: int
    version: int
    slug: str


class RuleCatalogLoader:
    """Load immutable compiled catalogs from DB; cache key = checksum."""

    def __init__(self) -> None:
        self._by_checksum: dict[str, LoadedRuleCatalog] = {}
        self._active_pin: tuple[int, str] | None = None

    def clear_cache(self) -> None:
        self._by_checksum.clear()
        self._active_pin = None

    def peek_cache(self, checksum: str) -> LoadedRuleCatalog | None:
        return self._by_checksum.get(checksum)

    def remember_active_pin(self, rule_set_version_id: int, checksum: str) -> None:
        self._active_pin = (rule_set_version_id, checksum)

    def peek_active_pin(self) -> tuple[int, str] | None:
        return self._active_pin

    async def load(
        self,
        session: AsyncSession,
        *,
        rule_set_version_id: int,
        checksum: str,
    ) -> LoadedRuleCatalog:
        if not checksum:
            raise RuleSetInvalidError("missing_checksum")

        cached = self._by_checksum.get(checksum)
        if cached is not None:
            if cached.rule_set_version_id != rule_set_version_id:
                raise RuleSetInvalidError("checksum_version_mismatch")
            return cached

        version = await session.get(RuleSetVersion, rule_set_version_id)
        if version is None:
            raise RuleSetInvalidError("missing_rule_set_version")
        if version.checksum != checksum:
            raise RuleSetInvalidError("checksum_mismatch")

        result = await session.execute(
            select(MonitoringRule)
            .where(
                MonitoringRule.rule_set_version_id == rule_set_version_id,
                MonitoringRule.enabled.is_(True),
            )
            # Rows are inserted in immutable catalog order; id preserves that order
            # and therefore the checksum pinned by the run.
            .order_by(MonitoringRule.id.asc())
        )
        rows = list(result.scalars().all())
        if not rows:
            raise RuleSetInvalidError("empty_rule_catalog")

        rules = tuple(
            SeedRule(
                stable_rule_id=row.stable_rule_id,
                priority=row.priority,
                target=row.target,
                dimension=row.dimension,
                weight=row.weight,
                pattern=row.pattern,
                explanation_code=row.explanation_code,
                kind=row.kind,
            )
            for row in rows
        )
        content_checksum = catalog_checksum(rules)
        if content_checksum != checksum:
            raise RuleSetInvalidError("catalog_content_checksum_mismatch")

        loaded = LoadedRuleCatalog(
            rule_set_version_id=version.id,
            checksum=version.checksum,
            rules=rules,
            hot_min=version.hot_min,
            warm_min=version.warm_min,
            cold_min=version.cold_min,
            version=version.version,
            slug=version.slug,
        )
        self._by_checksum[checksum] = loaded
        return loaded


_DEFAULT_LOADER = RuleCatalogLoader()


def get_default_loader() -> RuleCatalogLoader:
    return _DEFAULT_LOADER
