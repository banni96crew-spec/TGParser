from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *
from telegram_lead_discovery.detection.catalog import SeedRule


class _CancelRequested(Exception):
    """Internal control: operator cancel observed between network calls."""


class _FloodWaitControl(Exception):
    def __init__(self, until: datetime, query: DiscoveryRunQuery) -> None:
        self.until = until
        self.query = query
        super().__init__(until.isoformat())


class _SessionFatal(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class _WorkerContext:
    session: AsyncSession
    gateway: TelegramGateway
    job: Job
    run: DiscoveryRun
    profile_version: KeywordDiscoveryProfileVersion
    post_queries: tuple[str, ...]
    directory_queries: tuple[str, ...]
    replacement_directory_queries: tuple[str, ...]
    additional_exclusions: tuple[str, ...]
    required_service_profiles: tuple[str, ...]
    detection_rules: tuple[SeedRule, ...]
    rule_set_checksum: str
    registry: SourceRegistryIndex
    dismissed: DismissedKeywordSourceIndex
    directory_sources: list[SourceSnapshot]
    linked_parents: dict[int, int]
    last_heartbeat_at: datetime
    public_posts_quota_exhausted: bool = False
    registry_suppressed_ids: set[int] = field(default_factory=set)
    dismissed_suppressed_ids: set[int] = field(default_factory=set)
    presented_suppressed_ids: set[int] = field(default_factory=set)
    presented: PresentedKeywordSourceIndex = field(default_factory=PresentedKeywordSourceIndex)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _loads_counters(raw: str | None) -> dict[str, int | str]:
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        return {}
    out: dict[str, int | str] = {}
    for k, v in data.items():
        key = str(k)
        if isinstance(v, bool):
            out[key] = int(v)
        elif isinstance(v, int | float):
            out[key] = int(v)
        elif isinstance(v, str):
            # Preserve gate/reason labels (D-068); do not coerce to int.
            out[key] = v
    return out


def _dumps_counters(counters: dict[str, int | str]) -> str:
    return json.dumps(counters, ensure_ascii=False, sort_keys=True)


def _cursor_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_cursor(query: DiscoveryRunQuery, payload: dict[str, Any]) -> None:
    query.cursor_json = json.dumps(payload, ensure_ascii=False)


def _search_cursor_from_payload(payload: dict[str, Any]) -> SearchCursor | None:
    token = payload.get("token")
    if token is None or token == "":
        return None
    return SearchCursor(schema_version=1, token=str(token))


def _transient_delay_seconds(attempt: int) -> int:
    """attempt is 1-based failed attempt count before scheduling next wait."""
    idx = min(max(attempt, 1), len(RUNTIME_CONFIG.TRANSIENT_RETRY_DELAYS_S)) - 1
    return RUNTIME_CONFIG.TRANSIENT_RETRY_DELAYS_S[idx]
