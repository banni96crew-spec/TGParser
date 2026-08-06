"""Dashboard health API and page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from telegram_lead_discovery.dashboard.view_helpers import _template
from telegram_lead_discovery.observability.active_chat_metrics import (
    active_chat_terminal_metric_samples,
    terminal_metrics_payload,
)
from telegram_lead_discovery.observability.health import get_health_registry
from telegram_lead_discovery.observability.loops import (
    NAMED_RUNTIME_LOOPS,
    ensure_named_loop_components,
    named_loop_views,
)
from telegram_lead_discovery.storage.db import session_scope


def create_health_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    async def health_live() -> dict[str, object]:
        return get_health_registry().live_payload()

    @router.get("/health/ready")
    async def health_ready() -> JSONResponse:
        registry = get_health_registry()
        payload = registry.ready_payload()
        code = 200 if payload["status"] == "ready" else 503
        return JSONResponse(payload, status_code=code)

    @router.get("/metrics/discovery/active-chat")
    async def active_chat_metrics() -> dict[str, object]:
        async with session_scope() as session:
            samples = await active_chat_terminal_metric_samples(session)
        return terminal_metrics_payload(samples)

    return router


def create_health_page_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request) -> HTMLResponse:
        registry = ensure_named_loop_components(get_health_registry())
        components = {
            name: status.state.value for name, status in registry.components.items()
        }
        # Always expose named loops even if other components dominate.
        for loop_name in NAMED_RUNTIME_LOOPS:
            components.setdefault(loop_name, "starting")
        loops = [
            {
                "name": v.name,
                "state": v.state,
                "reason_code": v.reason_code,
                "heartbeat_at": v.heartbeat_at,
            }
            for v in named_loop_views(registry)
        ]
        degraded = any(v["state"] in {"degraded", "blocked", "unhealthy"} for v in loops)
        return _template(
            request,
            "health.html",
            {
                "title": "Состояние системы",
                "components": components,
                "named_loops": loops,
                "is_degraded": degraded,
                "readiness": registry.readiness.value,
            },
        )

    return router
