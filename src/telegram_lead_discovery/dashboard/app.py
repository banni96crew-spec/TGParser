from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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
    get_active_rule_pin,
    list_inbox_leads,
    update_lead_status,
)
from telegram_lead_discovery.observability.health import get_health_registry
from telegram_lead_discovery.observability.loops import (
    NAMED_RUNTIME_LOOPS,
    ensure_named_loop_components,
    named_loop_views,
)
from telegram_lead_discovery.security.csrf import generate_csrf_token, validate_csrf_token
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.settings.service import (
    SettingsValidationError,
    SettingsVersionConflict,
    snapshot,
    update_setting,
)
from telegram_lead_discovery.source_discovery.service import (
    REJECT_REASON_CODES,
    SourceLifecycleError,
    approve_source,
    disable_source,
    list_sources,
    pause_source,
    reconsider_source,
    reject_source,
    resume_source,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    CollectorCheckpoint,
    Job,
    Lead,
    LeadScore,
    LeadScoreComponent,
    RuleSetVersion,
    TelegramMessage,
    TelegramSource,
)

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

MONITORING_COVERAGE_LIMIT = 100
_BACKLOG_JOB_TYPES = frozenset(
    {"initial_backfill", "collector_backfill", "reconciliation"}
)


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


async def _monitoring_coverage_rows(session) -> list[dict[str, object]]:
    sources = (
        await session.execute(
            select(TelegramSource)
            .where(TelegramSource.lifecycle_state.in_(("monitoring", "paused")))
            .order_by(TelegramSource.id.asc())
            .limit(MONITORING_COVERAGE_LIMIT)
        )
    ).scalars().all()
    if not sources:
        return []
    source_ids = [s.id for s in sources]
    checkpoints = {
        c.source_id: c
        for c in (
            await session.execute(
                select(CollectorCheckpoint).where(
                    CollectorCheckpoint.source_id.in_(source_ids)
                )
            )
        ).scalars().all()
    }
    jobs = (
        await session.execute(
            select(Job).where(
                Job.job_type.in_(tuple(_BACKLOG_JOB_TYPES)),
                Job.state.in_(("queued", "running", "lease_expired", "retry_wait")),
            )
        )
    ).scalars().all()
    backlog_by_source: dict[int, int] = {}
    error_by_source: dict[int, str | None] = {}
    for job in jobs:
        try:
            payload = json.loads(job.payload_json or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        sid = payload.get("source_id")
        if sid is None:
            continue
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            continue
        backlog_by_source[sid_i] = backlog_by_source.get(sid_i, 0) + 1
        if job.last_error_code:
            error_by_source[sid_i] = job.last_error_code
    rows: list[dict[str, object]] = []
    for source in sources:
        cp = checkpoints.get(source.id)
        rows.append(
            {
                "id": source.id,
                "username": source.username_normalized,
                "title": source.title,
                "lifecycle_state": source.lifecycle_state,
                "access_error_code": source.access_error_code,
                "last_checked_at": source.last_checked_at,
                "checkpoint_message_id": (
                    cp.last_committed_message_id if cp is not None else None
                ),
                "checkpoint_published_at": (
                    cp.last_committed_published_at if cp is not None else None
                ),
                "last_reconciled_at": cp.last_reconciled_at if cp is not None else None,
                "backlog_jobs": backlog_by_source.get(source.id, 0),
                "job_error_code": error_by_source.get(source.id)
                or source.access_error_code,
                "has_error": bool(
                    source.access_error_code or error_by_source.get(source.id)
                ),
            }
        )
    return rows


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
            rule_pin = await get_active_rule_pin(session)
        return {
            "title": "Inbox",
            "leads": _lead_rows(page.leads),
            "band_filter": band,
            "next_cursor": page.next_cursor,
            "limit": page.limit,
            "csrf_token": token,
            "rule_pin": _rule_pin_dict(rule_pin),
            "is_empty": len(page.leads) == 0,
        }

    @app.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return _template(request, "home.html", ctx)

    @app.get("/inbox/fragment", response_class=HTMLResponse)
    async def inbox_fragment(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return _template(request, "inbox_fragment.html", ctx)

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
            rule_pin = await get_active_rule_pin(session)
            score_rule_version = None
            score_rule_checksum = None
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
                    score_rule_version = score.rule_set_version_id
                    ruleset = await session.get(RuleSetVersion, score.rule_set_version_id)
                    if ruleset is not None:
                        score_rule_checksum = ruleset.checksum
            source = None
            if message is not None:
                source = await session.get(TelegramSource, message.source_id)
            lead_view = {
                "id": lead.id,
                "band": lead.band,
                "category": lead.category,
                "status": lead.status,
                "rule_set_version_id": score_rule_version,
                "rule_set_checksum": score_rule_checksum,
            }
        return _template(
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
                "rule_pin": _rule_pin_dict(rule_pin),
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
        return _template(
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
            coverage = await _monitoring_coverage_rows(session)
        return _template(
            request,
            "sources.html",
            {
                "title": "Источники",
                "sources": sources,
                "csrf_token": token,
                "reject_reasons": sorted(REJECT_REASON_CODES),
                "monitoring_coverage": coverage,
                "monitoring_limit": MONITORING_COVERAGE_LIMIT,
                "is_empty": len(sources) == 0,
            },
        )

    @app.get("/sources/monitoring", response_class=HTMLResponse)
    async def sources_monitoring_page(request: Request) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            coverage = await _monitoring_coverage_rows(session)
        return _template(
            request,
            "monitoring.html",
            {
                "title": "Покрытие мониторинга",
                "csrf_token": token,
                "monitoring_coverage": coverage,
                "monitoring_limit": MONITORING_COVERAGE_LIMIT,
                "is_empty": len(coverage) == 0,
            },
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
        try:
            async with session_scope() as session:
                await approve_source(session, source_id=source_id, gateway=gateway)
        except (KeyError, ValueError) as exc:
            return HTMLResponse(str(exc), status_code=422)
        return RedirectResponse(url="/sources", status_code=303)

    async def _lifecycle_post(
        request: Request,
        *,
        source_id: int,
        csrf_token: str,
        action,
        **kwargs,
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                await action(session, source_id=source_id, **kwargs)
        except KeyError:
            return HTMLResponse("Источник не найден", status_code=404)
        except SourceLifecycleError as exc:
            return HTMLResponse(str(exc), status_code=422)
        except ValueError as exc:
            return HTMLResponse(str(exc), status_code=422)
        return RedirectResponse(url="/sources", status_code=303)

    @app.post("/sources/{source_id}/reject")
    async def sources_reject(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
        reason_code: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        return await _lifecycle_post(
            request,
            source_id=source_id,
            csrf_token=csrf_token,
            action=reject_source,
            reason_code=reason_code,
            note=note,
        )

    @app.post("/sources/{source_id}/reconsider")
    async def sources_reconsider(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        return await _lifecycle_post(
            request,
            source_id=source_id,
            csrf_token=csrf_token,
            action=reconsider_source,
            note=note,
        )

    @app.post("/sources/{source_id}/pause")
    async def sources_pause(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        return await _lifecycle_post(
            request,
            source_id=source_id,
            csrf_token=csrf_token,
            action=pause_source,
            note=note,
        )

    @app.post("/sources/{source_id}/resume")
    async def sources_resume(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        return await _lifecycle_post(
            request,
            source_id=source_id,
            csrf_token=csrf_token,
            action=resume_source,
            note=note,
        )

    @app.post("/sources/{source_id}/disable")
    async def sources_disable(
        request: Request,
        source_id: int,
        csrf_token: str = Form(...),
        note: str | None = Form(default=None),
    ) -> HTMLResponse:
        return await _lifecycle_post(
            request,
            source_id=source_id,
            csrf_token=csrf_token,
            action=disable_source,
            note=note,
        )

    @app.get("/health", response_class=HTMLResponse)
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

    @app.get("/settings", response_class=HTMLResponse)
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

    from telegram_lead_discovery.dashboard.discovery_routes import create_discovery_router

    app.include_router(create_discovery_router(templates))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
