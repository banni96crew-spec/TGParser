"""Graph discovery run page rendered from the existing discovery URL."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from telegram_lead_discovery.dashboard.discovery.http_helpers import _render_discovery
from telegram_lead_discovery.storage.models import DiscoveryRun

_GRAPH_CANCEL_STATES = frozenset({"queued", "running", "cancelling"})


def render_graph_run_page(
    templates: Jinja2Templates,
    request: Request,
    run: DiscoveryRun,
    csrf_token: str,
) -> HTMLResponse:
    counters = _counters(run.counters_json)
    return _render_discovery(
        templates,
        request,
        "discovery/graph_run_detail.html",
        {
            "title": f"Граф #{run.id}",
            "csrf_token": csrf_token,
            "run_id": run.id,
            "run": {
                "id": run.id,
                "state": run.state,
                "phase": run.phase,
                "version": run.version,
                "last_error_code": run.last_error_code,
                "run_termination_reason": run.run_termination_reason,
                "counters": counters,
                "can_cancel": run.state in _GRAPH_CANCEL_STATES,
            },
        },
    )


def _counters(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
