from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from telegram_lead_discovery.dashboard.export_csv import (
    ExportPreview,
    build_export_rows,
    count_export_rows,
    write_export_file,
)
from telegram_lead_discovery.dashboard.leads import (
    ALLOWED_STATUSES,
    list_inbox_leads,
    update_lead_status,
)
from telegram_lead_discovery.observability.health import get_health_registry
from telegram_lead_discovery.security.csrf import generate_csrf_token, validate_csrf_token
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.settings.service import (
    SettingsValidationError,
    SettingsVersionConflict,
    snapshot,
    update_setting,
)
from telegram_lead_discovery.source_discovery.service import approve_source, list_sources
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    Lead,
    LeadScore,
    LeadScoreComponent,
    TelegramMessage,
    TelegramSource,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def create_app(*, gateway=None) -> FastAPI:
    app = FastAPI(title="Telegram Lead Discovery", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key="local-only-dev-key")
    app.state.gateway = gateway

    @app.get("/health/live")
    async def health_live() -> dict[str, object]:
        return get_health_registry().live_payload()

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        registry = get_health_registry()
        payload = registry.ready_payload()
        code = 200 if payload["status"] == "ready" else 503
        return JSONResponse(payload, status_code=code)

    async def _inbox_context(
        request: Request,
        *,
        band: str | None,
        cursor: str | None,
        limit: int | None,
    ) -> dict:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            page = await list_inbox_leads(
                session, band=band, cursor=cursor, limit=limit
            )
        return {
            "title": "Inbox",
            "leads": _lead_rows(page.leads),
            "band_filter": band,
            "next_cursor": page.next_cursor,
            "limit": page.limit,
            "csrf_token": token,
        }

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return templates.TemplateResponse(request, "home.html", ctx)

    @app.get("/inbox/fragment", response_class=HTMLResponse)
    async def inbox_fragment(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return templates.TemplateResponse(request, "inbox_fragment.html", ctx)

    @app.get("/leads/{lead_id}", response_class=HTMLResponse)
    async def lead_detail(request: Request, lead_id: int) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                return HTMLResponse("Лид не найден", status_code=404)
            message = await session.get(TelegramMessage, lead.canonical_message_id)
            score = None
            components: list[dict] = []
            if lead.current_score_id is not None:
                score = await session.get(LeadScore, lead.current_score_id)
                if score is not None:
                    comp_result = await session.execute(
                        select(LeadScoreComponent).where(
                            LeadScoreComponent.lead_score_id == score.id
                        )
                    )
                    components = [
                        {
                            "rule_id": c.rule_id,
                            "dimension": c.dimension,
                            "value": c.value,
                            "reason_ru": c.reason_ru,
                        }
                        for c in comp_result.scalars()
                    ]
            source = None
            if message is not None:
                source = await session.get(TelegramSource, message.source_id)
            lead_view = {
                "id": lead.id,
                "band": lead.band,
                "category": lead.category,
                "status": lead.status,
            }
        return templates.TemplateResponse(
            request,
            "lead_detail.html",
            {
                "title": f"Лид #{lead_id}",
                "lead": lead_view,
                "message": message,
                "score": score,
                "components": components,
                "source": source,
                "csrf_token": token,
                "allowed_statuses": sorted(ALLOWED_STATUSES),
            },
        )

    @app.post("/leads/{lead_id}/status")
    async def lead_status_update(
        request: Request,
        lead_id: int,
        status: str = Form(...),
        csrf_token: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                await update_lead_status(
                    session, lead_id=lead_id, to_status=status, note=note
                )
        except KeyError:
            return HTMLResponse("Лид не найден", status_code=404)
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=422)
        return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)

    @app.get("/exports/leads")
    async def exports_leads_get() -> HTMLResponse:
        return HTMLResponse(
            "Экспорт создаётся только через POST после preview",
            status_code=405,
        )

    @app.post("/exports/leads/preview")
    async def exports_leads_preview(
        request: Request,
        csrf_token: str = Form(...),
        band: str | None = Form(default=None),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        async with session_scope() as session:
            count = await count_export_rows(session, band=band or None)
        preview = ExportPreview(
            row_count=count,
            columns=tuple(
                [
                    "lead_id",
                    "published_at",
                    "category",
                    "score",
                    "band",
                    "status",
                    "source_title",
                    "source_username",
                    "author_username",
                    "text",
                    "permalink",
                    "reasons",
                ]
            ),
            band_filter=band,
        )
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        request.session["export_preview_count"] = preview.row_count
        request.session["export_preview_band"] = band
        return templates.TemplateResponse(
            request,
            "export_preview.html",
            {
                "title": "Preview экспорта",
                "preview": preview,
                "csrf_token": token,
            },
        )

    @app.post("/exports/leads")
    async def exports_leads_create(
        request: Request,
        csrf_token: str = Form(...),
        confirm: str = Form(...),
        band: str | None = Form(default=None),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        if confirm.strip().upper() not in {"YES", "ДА", "CONFIRM"}:
            return HTMLResponse("Требуется подтверждение экспорта", status_code=400)
        async with session_scope() as session:
            rows = await build_export_rows(session, band=band or None)
            path = write_export_file(rows)
        return HTMLResponse(
            f"Экспорт сохранён: {path.name} ({len(rows)} строк)",
            status_code=200,
        )

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_page(request: Request) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            sources = await list_sources(session)
        return templates.TemplateResponse(
            request,
            "sources.html",
            {"title": "Источники", "sources": sources, "csrf_token": token},
        )

    @app.post("/sources/{source_id}/approve")
    async def sources_approve(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        gateway = getattr(request.app.state, "gateway", None)
        if gateway is None:
            return HTMLResponse("Gateway не настроен", status_code=503)
        async with session_scope() as session:
            await approve_source(session, source_id=source_id, gateway=gateway)
        return RedirectResponse(url="/sources", status_code=303)

    @app.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request) -> HTMLResponse:
        registry = get_health_registry()
        components = {
            name: status.state.value for name, status in registry.components.items()
        } or {
            "database": "healthy",
            "collector": "starting",
            "outbox": "healthy",
            "jobs": "healthy",
        }
        return templates.TemplateResponse(
            request,
            "health.html",
            {"title": "Состояние системы", "components": components},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            snap = await snapshot(session)
        presence = read_secret_presence()
        return templates.TemplateResponse(
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

    @app.post("/settings")
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

    return app
