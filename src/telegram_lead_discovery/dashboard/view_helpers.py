"""Shared Jinja and presentation helpers for the dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from telegram_lead_discovery.security.csrf import validate_csrf_token
from telegram_lead_discovery.storage.models import Lead

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def active_nav(path: str) -> str:
    """Map request path to sidebar nav key (inbox|sources|discovery|health|settings)."""
    if path.startswith("/sources"):
        return "sources"
    if path.startswith("/discovery"):
        return "discovery"
    if path == "/health":
        return "health"
    if path.startswith("/settings"):
        return "settings"
    return "inbox"


def health_status_class(state: str) -> str:
    """Map component health state to CSS status token class."""
    if state == "healthy":
        return "status-ok"
    if state in {"starting", "degraded", "stopped"}:
        return "status-warn"
    if state in {"blocked", "unhealthy"}:
        return "status-critical"
    return "status-warn"


templates.env.globals["health_status_class"] = health_status_class


def _template(
    request: Request, name: str, context: dict[str, object]
) -> HTMLResponse:
    payload = {**context, "active_nav": active_nav(request.url.path)}
    return templates.TemplateResponse(request, name, payload)


def _lead_rows(leads: list[Lead]) -> list[dict]:
    rows = []
    for lead in leads:
        rows.append(
            {
                "id": lead.id,
                "band": lead.band,
                "category": lead.category,
                "status": lead.status,
                "last_activity_at": lead.last_activity_at,
            }
        )
    return rows


def _csrf_or_403(request: Request, csrf_token: str) -> HTMLResponse | None:
    expected = request.session.get("csrf_token")
    if not validate_csrf_token(expected, csrf_token):
        return HTMLResponse("CSRF отклонён", status_code=403)
    return None


def _rule_pin_dict(pin) -> dict[str, object]:
    return {
        "version_id": pin.version_id,
        "version_label": pin.version_label,
        "checksum": pin.checksum,
    }
