"""Operator-settings dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from telegram_lead_discovery.dashboard.view_helpers import _csrf_or_403, _template
from telegram_lead_discovery.security.csrf import generate_csrf_token
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.settings.service import (
    SettingsValidationError,
    SettingsVersionConflict,
    snapshot,
    update_setting,
)
from telegram_lead_discovery.storage.db import session_scope


def create_settings_router() -> APIRouter:
    router = APIRouter()

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            snap = await snapshot(session)
        presence = read_secret_presence()
        return _template(
            request,
            "settings.html",
            {
                "title": "Настройки",
                "snapshot": snap,
                "csrf_token": token,
                "secrets": {
                    "TG_API_ID": "настроен" if presence.tg_api_id else "не настроен",
                    "TG_API_HASH": "настроен" if presence.tg_api_hash else "не настроен",
                    "TG_BOT_TOKEN": "настроен" if presence.tg_bot_token else "не настроен",
                    "TG_NOTIFY_CHAT_ID": "настроен"
                    if presence.tg_notify_chat_id
                    else "не настроен",
                },
            },
        )

    @router.post("/settings")
    async def settings_update(
        request: Request,
        key: str = Form(...),
        value: str = Form(...),
        expected_settings_version: int = Form(...),
        csrf_token: str = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        parsed: object
        if value in {"shadow", "live"}:
            parsed = value
        elif value.isdigit():
            parsed = int(value)
        else:
            parsed = value
        try:
            async with session_scope() as session:
                await update_setting(
                    session,
                    key=key,
                    value=parsed,
                    expected_settings_version=expected_settings_version,
                    source="ui",
                )
        except SettingsVersionConflict:
            return HTMLResponse("Конфликт версии настроек", status_code=409)
        except SettingsValidationError as exc:
            return HTMLResponse(str(exc), status_code=400)
        return await settings_page(request)

    return router
