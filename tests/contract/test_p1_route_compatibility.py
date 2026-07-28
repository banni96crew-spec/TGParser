"""Dashboard import and route contracts required by the P1 decomposition."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from typing import Any

APP_MODULE = "telegram_lead_discovery.dashboard.app"
DISCOVERY_MODULE = "telegram_lead_discovery.dashboard.discovery_routes"

DISCOVERY_EXPORTS = (
    "CONFIRM_RECONSIDER_SUPPRESS",
    "EVIDENCE_RETENTION_MESSAGE",
    "VERSION_CONFLICT_MESSAGE",
    "ZERO_STARS_LABEL",
    "create_discovery_router",
)

APP_REQUIRED_SYMBOLS = (
    "MONITORING_COVERAGE_LIMIT",
    "STATIC_DIR",
    "TEMPLATES_DIR",
    "active_nav",
    "create_app",
    "health_status_class",
    "templates",
    "_csrf_or_403",
    "_lead_rows",
    "_monitoring_coverage_rows",
    "_rule_pin_dict",
    "_template",
)

DISCOVERY_REQUIRED_SYMBOLS = (
    *DISCOVERY_EXPORTS,
    "_aliases_for_source",
    "_apply_band_filter",
    "_csrf_or_403",
    "_evidence_item",
    "_lifecycle_map",
    "_normalize_band_filter",
    "_opportunity_view",
    "_quota_summary",
    "_run_progress",
    "_run_view",
    "_suppress_for_opportunity",
)

MOVED_SYMBOLS = {
    (
        APP_MODULE,
        "telegram_lead_discovery.dashboard.app_factory",
    ): ("create_app",),
    (
        APP_MODULE,
        "telegram_lead_discovery.dashboard.view_helpers",
    ): (
        "STATIC_DIR",
        "TEMPLATES_DIR",
        "active_nav",
        "health_status_class",
        "templates",
        "_csrf_or_403",
        "_lead_rows",
        "_rule_pin_dict",
        "_template",
    ),
    (
        APP_MODULE,
        "telegram_lead_discovery.dashboard.monitoring_queries",
    ): (
        "MONITORING_COVERAGE_LIMIT",
        "_monitoring_coverage_rows",
    ),
    (
        DISCOVERY_MODULE,
        "telegram_lead_discovery.dashboard.discovery.constants",
    ): (
        "CONFIRM_RECONSIDER_SUPPRESS",
        "EVIDENCE_RETENTION_MESSAGE",
        "VERSION_CONFLICT_MESSAGE",
        "ZERO_STARS_LABEL",
    ),
    (
        DISCOVERY_MODULE,
        "telegram_lead_discovery.dashboard.discovery.http_helpers",
    ): ("_csrf_or_403",),
    (
        DISCOVERY_MODULE,
        "telegram_lead_discovery.dashboard.discovery.view_models",
    ): (
        "_evidence_item",
        "_normalize_band_filter",
        "_opportunity_view",
        "_quota_summary",
        "_run_progress",
        "_run_view",
    ),
    (
        DISCOVERY_MODULE,
        "telegram_lead_discovery.dashboard.discovery.queries",
    ): (
        "_aliases_for_source",
        "_apply_band_filter",
        "_lifecycle_map",
        "_suppress_for_opportunity",
    ),
    (
        DISCOVERY_MODULE,
        "telegram_lead_discovery.dashboard.discovery.router",
    ): ("create_discovery_router",),
}

EXPECTED_ROUTES = (
    ("Route", "/openapi.json", ("GET", "HEAD"), "openapi", ""),
    ("APIRoute", "/health/live", ("GET",), "health_live", ""),
    ("APIRoute", "/health/ready", ("GET",), "health_ready", ""),
    ("APIRoute", "/", ("GET",), "home", "HTMLResponse"),
    ("APIRoute", "/inbox/fragment", ("GET",), "inbox_fragment", "HTMLResponse"),
    ("APIRoute", "/leads/{lead_id}", ("GET",), "lead_detail", "HTMLResponse"),
    ("APIRoute", "/leads/{lead_id}/status", ("POST",), "lead_status_update", ""),
    ("APIRoute", "/exports/leads", ("GET",), "exports_leads_get", ""),
    ("APIRoute", "/exports/leads/preview", ("POST",), "exports_leads_preview", ""),
    ("APIRoute", "/exports/leads", ("POST",), "exports_leads_create", ""),
    ("APIRoute", "/sources", ("GET",), "sources_page", "HTMLResponse"),
    (
        "APIRoute",
        "/sources/monitoring",
        ("GET",),
        "sources_monitoring_page",
        "HTMLResponse",
    ),
    ("APIRoute", "/sources/{source_id}/approve", ("POST",), "sources_approve", ""),
    ("APIRoute", "/sources/{source_id}/reject", ("POST",), "sources_reject", ""),
    (
        "APIRoute",
        "/sources/{source_id}/reconsider",
        ("POST",),
        "sources_reconsider",
        "",
    ),
    ("APIRoute", "/sources/{source_id}/pause", ("POST",), "sources_pause", ""),
    ("APIRoute", "/sources/{source_id}/resume", ("POST",), "sources_resume", ""),
    ("APIRoute", "/sources/{source_id}/disable", ("POST",), "sources_disable", ""),
    ("APIRoute", "/health", ("GET",), "health_page", "HTMLResponse"),
    ("APIRoute", "/settings", ("GET",), "settings_page", "HTMLResponse"),
    ("APIRoute", "/settings", ("POST",), "settings_update", ""),
    ("APIRoute", "/discovery", ("GET",), "discovery_index", "HTMLResponse"),
    (
        "APIRoute",
        "/discovery/profiles/new",
        ("GET",),
        "discovery_profile_new",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/profiles",
        ("POST",),
        "discovery_profile_create",
        "",
    ),
    (
        "APIRoute",
        "/discovery/profiles/{profile_id}",
        ("GET",),
        "discovery_profile_detail",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/profiles/{profile_id}/versions",
        ("POST",),
        "discovery_profile_version_create",
        "",
    ),
    ("APIRoute", "/discovery/runs", ("POST",), "discovery_run_start", ""),
    (
        "APIRoute",
        "/discovery/runs/{run_id}",
        ("GET",),
        "discovery_run_detail",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/runs/{run_id}/status-fragment",
        ("GET",),
        "discovery_run_status_fragment",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/runs/{run_id}/results-fragment",
        ("GET",),
        "discovery_run_results_fragment",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/runs/{run_id}/cancel",
        ("POST",),
        "discovery_run_cancel",
        "",
    ),
    (
        "APIRoute",
        "/discovery/results/{result_id}",
        ("GET",),
        "discovery_result_detail",
        "HTMLResponse",
    ),
    (
        "APIRoute",
        "/discovery/results/{result_id}/promote",
        ("POST",),
        "discovery_result_promote",
        "",
    ),
    (
        "APIRoute",
        "/discovery/results/{result_id}/dismiss",
        ("POST",),
        "discovery_result_dismiss",
        "",
    ),
    (
        "APIRoute",
        "/discovery/results/{result_id}/reconsider-suppress",
        ("POST",),
        "discovery_result_reconsider_suppress",
        "",
    ),
    ("Mount", "/static", (), "static", ""),
)


def _route_snapshot(route: Any) -> tuple[str, str, tuple[str, ...], str, str]:
    response_class = getattr(route, "response_class", None)
    return (
        type(route).__name__,
        route.path,
        tuple(sorted(getattr(route, "methods", ()) or ())),
        route.name,
        getattr(response_class, "__name__", ""),
    )


def test_p1_legacy_modules_keep_required_symbols() -> None:
    app_module = importlib.import_module(APP_MODULE)
    discovery_module = importlib.import_module(DISCOVERY_MODULE)

    assert not [name for name in APP_REQUIRED_SYMBOLS if not hasattr(app_module, name)]
    assert not [
        name for name in DISCOVERY_REQUIRED_SYMBOLS if not hasattr(discovery_module, name)
    ]
    assert tuple(discovery_module.__all__) == DISCOVERY_EXPORTS


def test_p1_moved_symbols_keep_object_identity_at_legacy_paths() -> None:
    for (legacy_module_name, leaf_module_name), names in MOVED_SYMBOLS.items():
        legacy_module = importlib.import_module(legacy_module_name)
        leaf_module = importlib.import_module(leaf_module_name)
        for name in names:
            assert getattr(legacy_module, name) is getattr(leaf_module, name)


def test_p1_factory_and_de_facto_helper_signatures_remain_stable() -> None:
    app_module = importlib.import_module(APP_MODULE)
    discovery_module = importlib.import_module(DISCOVERY_MODULE)
    expected = {
        app_module.create_app: ("gateway",),
        discovery_module.create_discovery_router: ("templates",),
        discovery_module._quota_summary: ("request",),
        discovery_module._normalize_band_filter: ("band",),
        discovery_module._opportunity_view: (
            "row",
            "lifecycle_state",
            "aliases",
            "suppress",
        ),
    }
    for callable_object, parameters in expected.items():
        assert tuple(inspect.signature(callable_object).parameters) == parameters


def test_p1_ordered_route_inventory_remains_stable() -> None:
    app_module = importlib.import_module(APP_MODULE)
    app = app_module.create_app()

    assert tuple(_route_snapshot(route) for route in app.routes) == EXPECTED_ROUTES


def test_p1_app_wiring_and_view_tokens_remain_stable() -> None:
    app_module = importlib.import_module(APP_MODULE)
    gateway = object()
    app = app_module.create_app(gateway=gateway)

    assert app.title == "Telegram Lead Discovery"
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.state.gateway is gateway
    assert app_module.TEMPLATES_DIR.name == "templates"
    assert app_module.STATIC_DIR.name == "static"
    assert app_module.templates.env.globals["health_status_class"] is (
        app_module.health_status_class
    )
    assert app_module.active_nav("/sources/monitoring") == "sources"
    assert app_module.active_nav("/discovery/runs/1") == "discovery"
    assert app_module.active_nav("/health") == "health"
    assert app_module.active_nav("/settings") == "settings"
    assert app_module.active_nav("/") == "inbox"
    assert app_module.health_status_class("healthy") == "status-ok"
    assert app_module.health_status_class("degraded") == "status-warn"
    assert app_module.health_status_class("blocked") == "status-critical"


def test_p1_leaf_modules_do_not_import_dashboard_facades() -> None:
    dashboard = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "telegram_lead_discovery"
        / "dashboard"
    )
    paths = [
        dashboard / "app_factory.py",
        dashboard / "monitoring_queries.py",
        dashboard / "view_helpers.py",
        *(dashboard / "routes").glob("*.py"),
        *(dashboard / "discovery").glob("*.py"),
    ]
    forbidden = {
        "telegram_lead_discovery.dashboard.app",
        "telegram_lead_discovery.dashboard.discovery_routes",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert forbidden.isdisjoint(imported_modules), path
