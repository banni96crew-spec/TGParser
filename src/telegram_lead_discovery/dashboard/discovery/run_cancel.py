"""Cancel dispatcher for keyword and graph discovery runs (UI-029)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.source_discovery.graph_cancel import (
    cancel_graph_discovery_run,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunNotFoundError,
    cancel_keyword_discovery_run,
)
from telegram_lead_discovery.storage.models import DiscoveryRun


async def execute_discovery_run_cancel(
    session: AsyncSession,
    *,
    run_id: int,
    expected_version: int,
) -> None:
    run = await session.get(DiscoveryRun, run_id)
    if run is None:
        raise KeywordRunNotFoundError(f"keyword_run_not_found:{run_id}")
    if run.run_type == "graph":
        await cancel_graph_discovery_run(
            session,
            run_id=run_id,
            expected_version=expected_version,
        )
        return
    if run.run_type == "keyword_scouting":
        await cancel_keyword_discovery_run(
            session,
            run_id=run_id,
            expected_version=expected_version,
        )
        return
    raise KeywordRunNotFoundError(f"keyword_run_not_found:{run_id}")
