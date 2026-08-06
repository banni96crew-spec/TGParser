"""SQL-derived terminal metrics for ActiveClientChat v1 (OBS-022)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_lead_discovery.storage.models import DiscoveryTerminalOutcome

TRUTH_STATUSES = ("quality", "near", "inconclusive", "rejected")
STOP_REASONS = (
    "quality_reached",
    "window_complete",
    "history_exhausted",
    "source_cap",
    "run_cap",
    "inaccessible",
    "cancelled",
)
THRESHOLD_COLUMNS = (
    ("activity_messages", DiscoveryTerminalOutcome.threshold_activity_messages),
    ("activity_days", DiscoveryTerminalOutcome.threshold_activity_days),
    ("activity_authors", DiscoveryTerminalOutcome.threshold_activity_authors),
    ("client_requests", DiscoveryTerminalOutcome.threshold_client_requests),
    ("client_authors", DiscoveryTerminalOutcome.threshold_client_authors),
    ("freshness", DiscoveryTerminalOutcome.threshold_freshness),
)


@dataclass(frozen=True, slots=True)
class TerminalMetricSample:
    name: str
    value: int
    labels: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def active_chat_terminal_metric_samples(
    session: AsyncSession,
) -> tuple[TerminalMetricSample, ...]:
    """Aggregate retained immutable outcomes on every scrape; no process counters."""
    truth_rows = (
        await session.execute(
            select(
                DiscoveryTerminalOutcome.truth_status,
                func.count(DiscoveryTerminalOutcome.id),
            ).group_by(DiscoveryTerminalOutcome.truth_status)
        )
    ).all()
    truth_counts = {str(status): int(count) for status, count in truth_rows}

    threshold_exprs = [
        func.sum(case((column.is_(True), 1), else_=0)).label(dimension)
        for dimension, column in THRESHOLD_COLUMNS
    ]
    aggregate_row = (
        await session.execute(
            select(
                *threshold_exprs,
                func.coalesce(
                    func.sum(DiscoveryTerminalOutcome.unknown_author_message_count),
                    0,
                ).label("unknown_author_messages"),
            )
        )
    ).one()

    stop_rows = (
        await session.execute(
            select(
                DiscoveryTerminalOutcome.verification_stop_reason,
                func.count(DiscoveryTerminalOutcome.id),
            ).group_by(DiscoveryTerminalOutcome.verification_stop_reason)
        )
    ).all()
    stop_counts = {str(reason): int(count) for reason, count in stop_rows}

    samples: list[TerminalMetricSample] = []
    for status in TRUTH_STATUSES:
        samples.append(
            TerminalMetricSample(
                "discovery_active_chat_candidates_total",
                truth_counts.get(status, 0),
                {"truth_status": status},
            )
        )
    samples.append(
        TerminalMetricSample(
            "discovery_active_chat_quality_total",
            truth_counts.get("quality", 0),
            {},
        )
    )
    for index, (dimension, _column) in enumerate(THRESHOLD_COLUMNS):
        samples.append(
            TerminalMetricSample(
                "discovery_active_chat_threshold_met_total",
                int(aggregate_row[index] or 0),
                {"dimension": dimension},
            )
        )
    samples.append(
        TerminalMetricSample(
            "discovery_active_chat_unknown_author_messages_total",
            int(aggregate_row.unknown_author_messages or 0),
            {},
        )
    )
    for reason in STOP_REASONS:
        samples.append(
            TerminalMetricSample(
                "discovery_active_chat_verification_stop_total",
                stop_counts.get(reason, 0),
                {"reason": reason},
            )
        )
    return tuple(samples)


def terminal_metrics_payload(
    samples: tuple[TerminalMetricSample, ...],
) -> dict[str, object]:
    return {
        "source": "discovery_terminal_outcomes",
        "retention_days": 90,
        "metrics": [sample.as_dict() for sample in samples],
    }


__all__ = [
    "STOP_REASONS",
    "THRESHOLD_COLUMNS",
    "TRUTH_STATUSES",
    "TerminalMetricSample",
    "active_chat_terminal_metric_samples",
    "terminal_metrics_payload",
]
