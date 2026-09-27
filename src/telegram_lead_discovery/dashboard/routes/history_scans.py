"""Manual history scan dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from telegram_lead_discovery.dashboard.view_helpers import _csrf_or_403, _template
from telegram_lead_discovery.processing.history_scan import (
    HistoryScanError,
    cancel_history_scan,
    create_history_scan,
)
from telegram_lead_discovery.security.csrf import generate_csrf_token
from telegram_lead_discovery.settings.service import get_setting
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    HistoryScanResult,
    HistoryScanSession,
    HistoryScanTarget,
    TelegramSource,
)


def create_history_scans_router() -> APIRouter:
    router = APIRouter()

    async def page(
        request: Request, *, message: str | None = None, status: int = 200
    ) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            enabled = bool(await get_setting(session, "history_scan.enabled"))
            sources = list(
                (
                    await session.execute(
                        select(TelegramSource)
                        .where(TelegramSource.lifecycle_state == "monitoring")
                        .order_by(TelegramSource.title.asc())
                    )
                ).scalars()
            )
            scans = list(
                (
                    await session.execute(
                        select(HistoryScanSession).order_by(HistoryScanSession.created_at.desc()).limit(20)
                    )
                ).scalars()
            )
        return _template(
            request,
            "history_scans.html",
            {
                "title": "Скан истории",
                "csrf_token": token,
                "enabled": enabled,
                "sources": sources,
                "scans": scans,
                "message": message,
            },
        )

    @router.get("/history-scans", response_class=HTMLResponse)
    async def history_scans_index(request: Request) -> HTMLResponse:
        return await page(request)

    @router.post("/history-scans")
    async def history_scans_start(
        request: Request,
        source_ids: list[int] = Form(...),  # noqa: B008
        period_hours: int = Form(...),
        csrf_token: str = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                if not bool(await get_setting(session, "history_scan.enabled")):
                    return await page(request, message="Сканирование выключено", status=403)
                scan = await create_history_scan(
                    session, source_ids=source_ids, period_hours=period_hours
                )
        except HistoryScanError as exc:
            return await page(request, message=str(exc), status=400)
        return RedirectResponse(f"/history-scans/{scan.id}", status_code=303)

    @router.get("/history-scans/{scan_id}", response_class=HTMLResponse)
    async def history_scan_detail(request: Request, scan_id: str) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        async with session_scope() as session:
            scan = await session.get(HistoryScanSession, scan_id)
            if scan is None:
                return HTMLResponse("Скан не найден", status_code=404)
            targets = list(
                (
                    await session.execute(
                        select(HistoryScanTarget)
                        .where(HistoryScanTarget.session_id == scan_id)
                        .order_by(HistoryScanTarget.source_title.asc())
                    )
                ).scalars()
            )
            results = list(
                (
                    await session.execute(
                        select(HistoryScanResult, HistoryScanTarget.source_title)
                        .join(
                            HistoryScanTarget,
                            HistoryScanTarget.id == HistoryScanResult.target_id,
                        )
                        .where(HistoryScanResult.session_id == scan_id)
                        .order_by(HistoryScanResult.published_at.desc())
                    )
                ).all()
            )
        return _template(
            request,
            "history_scan_detail.html",
            {
                "title": "Результаты скана",
                "csrf_token": token,
                "scan": scan,
                "targets": targets,
                "results": results,
            },
        )

    @router.post("/history-scans/{scan_id}/cancel")
    async def history_scan_cancel(
        request: Request, scan_id: str, csrf_token: str = Form(...)
    ) -> Response:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        async with session_scope() as session:
            cancelled = await cancel_history_scan(session, session_id=scan_id)
        if not cancelled:
            return HTMLResponse("Скан нельзя отменить", status_code=409)
        return RedirectResponse(f"/history-scans/{scan_id}", status_code=303)

    return router
