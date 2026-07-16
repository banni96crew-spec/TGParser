"""In-memory metric buckets with 5-minute windows (OBS-006)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

BUCKET_SECONDS = 300


def _bucket_start(now: datetime) -> datetime:
    epoch = int(now.timestamp())
    aligned = epoch - (epoch % BUCKET_SECONDS)
    return datetime.fromtimestamp(aligned, tz=UTC)


@dataclass
class Bucket:
    metric_name: str
    labels_key: str
    bucket_start: datetime
    count: int = 0
    sum: float = 0.0
    min_value: float | None = None
    max_value: float | None = None


@dataclass
class MetricsRegistry:
    buckets: dict[tuple[str, str, datetime], Bucket] = field(default_factory=dict)

    def observe(
        self,
        metric_name: str,
        value: float = 1.0,
        *,
        labels: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        clock = now or datetime.now(UTC)
        start = _bucket_start(clock)
        labels_key = _labels_key(labels or {})
        key = (metric_name, labels_key, start)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = Bucket(metric_name=metric_name, labels_key=labels_key, bucket_start=start)
            self.buckets[key] = bucket
        bucket.count += 1
        bucket.sum += value
        bucket.min_value = value if bucket.min_value is None else min(bucket.min_value, value)
        bucket.max_value = value if bucket.max_value is None else max(bucket.max_value, value)

    def cleanup(self, *, retain_days: int = 90, now: datetime | None = None) -> int:
        clock = now or datetime.now(UTC)
        cutoff = clock - timedelta(days=retain_days)
        to_delete = [k for k, b in self.buckets.items() if b.bucket_start < cutoff]
        for key in to_delete:
            del self.buckets[key]
        return len(to_delete)


def _labels_key(labels: dict[str, Any]) -> str:
    parts = [f"{k}={labels[k]}" for k in sorted(labels)]
    return ",".join(parts)


_metrics = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _metrics
