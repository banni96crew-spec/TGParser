"""Compatibility facade for source discovery services."""

from telegram_lead_discovery.source_discovery import csv_import as _csv_import
from telegram_lead_discovery.source_discovery import normalization as _normalization
from telegram_lead_discovery.source_discovery import source_candidates as _candidates
from telegram_lead_discovery.source_discovery import source_lifecycle as _lifecycle

USERNAME_RE = _normalization.USERNAME_RE
InvalidUsernameError = _normalization.InvalidUsernameError
normalize_username = _normalization.normalize_username

CsvImportRowResult = _csv_import.CsvImportRowResult
import_csv = _csv_import.import_csv

add_manual_candidate = _candidates.add_manual_candidate
list_sources = _candidates.list_sources

REJECT_REASON_CODES = _lifecycle.REJECT_REASON_CODES
SourceLifecycleError = _lifecycle.SourceLifecycleError
approve_source = _lifecycle.approve_source
_transition_source = _lifecycle._transition_source
reject_source = _lifecycle.reject_source
reconsider_source = _lifecycle.reconsider_source
pause_source = _lifecycle.pause_source
resume_source = _lifecycle.resume_source
disable_source = _lifecycle.disable_source
