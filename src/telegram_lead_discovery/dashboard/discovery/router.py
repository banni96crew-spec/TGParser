"""Assembly for keyword-discovery route groups."""

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from telegram_lead_discovery.dashboard.discovery.profile_routes import (
    create_profile_router,
)
from telegram_lead_discovery.dashboard.discovery.result_routes import (
    create_result_router,
)
from telegram_lead_discovery.dashboard.discovery.run_routes import create_run_router


def create_discovery_router(templates: Jinja2Templates) -> APIRouter:
    """Build discovery router bound to the dashboard Jinja environment."""
    router = APIRouter()
    router.include_router(create_profile_router(templates))
    router.include_router(create_run_router(templates))
    router.include_router(create_result_router(templates))
    return router
