"""Backfill PresentedKeywordSource.suppress_class (D-076 / STO-024)."""

from __future__ import annotations

from sqlalchemy import inspect, text

QUALITY = "quality"
NON_QUALITY = "non_quality"
LEGACY = "legacy_unspecified"
ALLOWED = (QUALITY, NON_QUALITY, LEGACY)


def backfill_from_live_snapshots(bind) -> None:
    tables = set(inspect(bind).get_table_names())
    if "presented_keyword_sources" not in tables:
        return
    if "source_opportunity_snapshots" not in tables:
        return
    bind.execute(
        text(
            "UPDATE presented_keyword_sources SET suppress_class = :quality "
            "WHERE EXISTS ("
            "SELECT 1 FROM source_opportunity_snapshots AS s "
            "WHERE s.truth_status = :quality AND ("
            "(presented_keyword_sources.source_telegram_id IS NOT NULL "
            "AND s.source_telegram_id = presented_keyword_sources.source_telegram_id) "
            "OR (presented_keyword_sources.origin_opportunity_id IS NOT NULL "
            "AND s.id = presented_keyword_sources.origin_opportunity_id)"
            "))"
        ),
        {"quality": QUALITY},
    )
