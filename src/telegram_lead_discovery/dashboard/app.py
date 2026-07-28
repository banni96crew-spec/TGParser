"""Compatibility facade for dashboard application assembly."""

from telegram_lead_discovery.dashboard import app_factory as _factory
from telegram_lead_discovery.dashboard import monitoring_queries as _monitoring
from telegram_lead_discovery.dashboard import view_helpers as _views

TEMPLATES_DIR = _views.TEMPLATES_DIR
STATIC_DIR = _views.STATIC_DIR
templates = _views.templates
active_nav = _views.active_nav
health_status_class = _views.health_status_class
_template = _views._template
_lead_rows = _views._lead_rows
_csrf_or_403 = _views._csrf_or_403
_rule_pin_dict = _views._rule_pin_dict

MONITORING_COVERAGE_LIMIT = _monitoring.MONITORING_COVERAGE_LIMIT
_BACKLOG_JOB_TYPES = _monitoring._BACKLOG_JOB_TYPES
_monitoring_coverage_rows = _monitoring._monitoring_coverage_rows

create_app = _factory.create_app
