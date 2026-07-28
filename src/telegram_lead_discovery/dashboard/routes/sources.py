"""Source listing, monitoring, and lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from telegram_lead_discovery.dashboard.monitoring_queries import (
    MONITORING_COVERAGE_LIMIT,
    _monitoring_coverage_rows,
)
from telegram_lead_discovery.dashboard.view_helpers import _csrf_or_403, _template
from telegram_lead_discovery.security.csrf import generate_csrf_token
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


def create_sources_router() -> APIRouter:
    router = APIRouter()

    @router.get("/sources", response_class=HTMLResponse)
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

    @router.get("/sources/monitoring", response_class=HTMLResponse)
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

    @router.post("/sources/{source_id}/approve")
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

    @router.post("/sources/{source_id}/reject")
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

    @router.post("/sources/{source_id}/reconsider")
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

    @router.post("/sources/{source_id}/pause")
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

    @router.post("/sources/{source_id}/resume")
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

    @router.post("/sources/{source_id}/disable")
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

    return router
