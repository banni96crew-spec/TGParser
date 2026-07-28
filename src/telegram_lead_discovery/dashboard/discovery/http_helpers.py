"""Shared HTTP and CSRF helpers for discovery routes."""

from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from telegram_lead_discovery.dashboard.discovery.constants import ZERO_STARS_LABEL
from telegram_lead_discovery.security.csrf import generate_csrf_token, validate_csrf_token
from telegram_lead_discovery.security.secrets import read_secret_presence


def _csrf_or_403(request: Request, csrf_token: str) -> HTMLResponse | None:
    expected = request.session.get("csrf_token")
    if not validate_csrf_token(expected, csrf_token):
        return HTMLResponse("CSRF отклонён", status_code=403)
    return None


def _issue_csrf(request: Request) -> str:
    token = generate_csrf_token()
    request.session["csrf_token"] = token
    return token


def _safe_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    correlation_id: str | None = None,
) -> HTMLResponse:
    cid = correlation_id or str(uuid.uuid4())
    body = f"{message} (код: {error_code}; correlation_id: {cid})"
    return HTMLResponse(body, status_code=status_code)


def _lines(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _credentials_present(request: Request) -> bool:
    flag = getattr(request.app.state, "telegram_credentials_present", None)
    if flag is not None:
        return bool(flag)
    presence = read_secret_presence()
    return bool(presence.tg_api_id and presence.tg_api_hash)


def _telegram_connection_state(request: Request) -> str:
    if not _credentials_present(request):
        return "credentials_missing"
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None:
        return "disconnected"
    return "connected"


def _render_discovery(
    templates: Jinja2Templates,
    request: Request,
    name: str,
    context: dict[str, object],
) -> HTMLResponse:
    payload = {
        **context,
        "active_nav": "discovery",
        "zero_stars_label": ZERO_STARS_LABEL,
    }
    return templates.TemplateResponse(request, name, payload)
