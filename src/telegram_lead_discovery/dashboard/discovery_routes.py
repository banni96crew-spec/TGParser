"""Compatibility facade for keyword-discovery dashboard routes."""

from telegram_lead_discovery.dashboard.discovery import constants as _constants
from telegram_lead_discovery.dashboard.discovery import http_helpers as _http
from telegram_lead_discovery.dashboard.discovery import queries as _queries
from telegram_lead_discovery.dashboard.discovery import router as _router
from telegram_lead_discovery.dashboard.discovery import view_models as _views

ZERO_STARS_LABEL = _constants.ZERO_STARS_LABEL
VERSION_CONFLICT_MESSAGE = _constants.VERSION_CONFLICT_MESSAGE
EVIDENCE_RETENTION_MESSAGE = _constants.EVIDENCE_RETENTION_MESSAGE
CONFIRM_RECONSIDER_SUPPRESS = _constants.CONFIRM_RECONSIDER_SUPPRESS

_TERMINAL_QUERY_STATES = _views._TERMINAL_QUERY_STATES
_ACTIVE_RUN_STATES = _views._ACTIVE_RUN_STATES
_SEED_QUERY_KINDS = _views._SEED_QUERY_KINDS
_DEFAULT_BANDS = _views._DEFAULT_BANDS
_BAND_FILTER_DEFAULT = _views._BAND_FILTER_DEFAULT
_POOL_REASON_BY_CODE = _views._POOL_REASON_BY_CODE
_FUNNEL_KEYS = _views._FUNNEL_KEYS
_TRUTH_LABELS = _views._TRUTH_LABELS
POOL_EXHAUSTED_REASON_CODES = _views.POOL_EXHAUSTED_REASON_CODES

_csrf_or_403 = _http._csrf_or_403
_issue_csrf = _http._issue_csrf
_safe_error = _http._safe_error
_lines = _http._lines
_credentials_present = _http._credentials_present
_telegram_connection_state = _http._telegram_connection_state

_quota_summary = _views._quota_summary
_loads_json_obj = _views._loads_json_obj
_run_view = _views._run_view
_run_progress = _views._run_progress
_rank_reason = _views._rank_reason
_eligibility_reasons = _views._eligibility_reasons
_normalize_band_filter = _views._normalize_band_filter
_truth_label = _views._truth_label
_sampling_label = _views._sampling_label
_opportunity_view = _views._opportunity_view
_evidence_item = _views._evidence_item

_apply_band_filter = _queries._apply_band_filter
_lifecycle_map = _queries._lifecycle_map
_aliases_for_source = _queries._aliases_for_source
_suppress_for_opportunity = _queries._suppress_for_opportunity

create_discovery_router = _router.create_discovery_router

__all__ = [
    "CONFIRM_RECONSIDER_SUPPRESS",
    "EVIDENCE_RETENTION_MESSAGE",
    "VERSION_CONFLICT_MESSAGE",
    "ZERO_STARS_LABEL",
    "create_discovery_router",
]
