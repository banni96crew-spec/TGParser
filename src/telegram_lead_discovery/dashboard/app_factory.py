"""FastAPI application assembly for the local dashboard."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from telegram_lead_discovery.dashboard.discovery.router import (
    create_discovery_router,
)
from telegram_lead_discovery.dashboard.routes.exports import create_exports_router
from telegram_lead_discovery.dashboard.routes.health import (
    create_health_api_router,
    create_health_page_router,
)
from telegram_lead_discovery.dashboard.routes.leads import create_leads_router
from telegram_lead_discovery.dashboard.routes.settings import create_settings_router
from telegram_lead_discovery.dashboard.routes.sources import create_sources_router
from telegram_lead_discovery.dashboard.view_helpers import STATIC_DIR, templates


def create_app(*, gateway=None) -> FastAPI:
    app = FastAPI(title="Telegram Lead Discovery", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key="local-only-dev-key")
    app.state.gateway = gateway

    app.include_router(create_health_api_router())
    app.include_router(create_leads_router())
    app.include_router(create_exports_router())
    app.include_router(create_sources_router())
    app.include_router(create_health_page_router())
    app.include_router(create_settings_router())
    app.include_router(create_discovery_router(templates))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
