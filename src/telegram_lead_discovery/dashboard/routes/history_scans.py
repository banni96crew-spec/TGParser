"""Manual history scan dashboard routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from telegram_lead_discovery.dashboard.view_helpers import _csrf_or_403, _template
from telegram_lead_discovery.processing.history_scan import (
    HistoryScanError,
    cancel_history_scan,
    create_history_scan,
    prepare_manual_history_targets,
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

HISTORY_SCAN_CATEGORY_LABELS = {
    "direct_order": "Прямой заказ",
    "contractor_search": "Поиск исполнителя",
    "recommendation_request": "Запрос рекомендации",
    "vacancy": "Вакансия",
}
HISTORY_SCAN_SCORE_BAND_LABELS = {
    "hot": "Высокая",
    "warm": "Тёплая",
    "cold": "Холодная",
    "irrelevant": "Нерелевантная",
}


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
        response = _template(
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
        response.status_code = status
        return response

    @router.get("/history-scans", response_class=HTMLResponse)
    async def history_scans_index(request: Request) -> HTMLResponse:
        return await page(request)

    @router.post("/history-scans")
    async def history_scans_start(
        request: Request,
        period_hours: int = Form(...),
        manual_refs: str = Form(""),
        csrf_token: str = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            form_data = await request.form()
            source_ids = [int(value) for value in form_data.getlist("source_ids")]
            gateway = getattr(request.app.state, "gateway", None)
            if manual_refs.strip() and gateway is None:
                return await page(request, message="Gateway не настроен", status=503)
            manual_targets, input_rejections = (
                await prepare_manual_history_targets(gateway, manual_refs)
                if manual_refs.strip()
                else ([], [])
            )
            async with session_scope() as session:
                if not bool(await get_setting(session, "history_scan.enabled")):
                    return await page(request, message="Сканирование выключено", status=403)
                scan = await create_history_scan(
                    session,
                    source_ids=source_ids,
                    period_hours=period_hours,
                    manual_targets=manual_targets,
                    input_rejections=input_rejections,
                )
        except HistoryScanError as exc:
            code = str(exc)
            return await page(
                request,
                message=code,
                status=429 if code.startswith("manual_source_rate_limited=") else 400,
            )
        return RedirectResponse(f"/history-scans/{scan.id}", status_code=303)

    @router.get("/history-scans/{scan_id}", response_class=HTMLResponse)
    async def history_scan_detail(request: Request, scan_id: str) -> HTMLResponse:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
        requested_category = request.query_params.get("category")
        selected_category = (
            requested_category
            if requested_category in HISTORY_SCAN_CATEGORY_LABELS
            else None
        )
        requested_score_band = request.query_params.get("score_band")
        selected_score_band = (
            requested_score_band
            if requested_score_band in HISTORY_SCAN_SCORE_BAND_LABELS
            else None
        )
        async with session_scope() as session:
            scan = await session.get(HistoryScanSession, scan_id)
            if scan is None:
                return HTMLResponse("Скан не найден", status_code=404)
            targets = list(
                (
                    await session.execute(
                        select(HistoryScanTarget)
                        .where(HistoryScanTarget.session_id == scan_id)
                        .order_by(HistoryScanTarget.ordinal.asc())
                    )
                ).scalars()
            )
            results_query = (
                select(HistoryScanResult, HistoryScanTarget.source_title)
                .join(
                    HistoryScanTarget,
                    HistoryScanTarget.id == HistoryScanResult.target_id,
                )
                .where(HistoryScanResult.session_id == scan_id)
            )
            if selected_category is not None:
                results_query = results_query.where(
                    HistoryScanResult.category == selected_category
                )
            if selected_score_band is not None:
                results_query = results_query.where(
                    HistoryScanResult.score_band == selected_score_band
                )
            results = list(
                (
                    await session.execute(
                        results_query.order_by(HistoryScanResult.published_at.desc())
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
                "selected_category": selected_category,
                "category_labels": HISTORY_SCAN_CATEGORY_LABELS,
                "selected_score_band": selected_score_band,
                "score_band_labels": HISTORY_SCAN_SCORE_BAND_LABELS,
                "input_rejections": json.loads(scan.input_rejections_json or "[]"),
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
