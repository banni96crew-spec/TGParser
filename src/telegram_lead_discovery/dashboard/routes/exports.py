"""Manual lead-export routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from telegram_lead_discovery.dashboard.export_csv import (
    ExportPreview,
    build_export_rows,
    count_export_rows,
    write_export_file,
)
from telegram_lead_discovery.dashboard.view_helpers import _csrf_or_403, _template
from telegram_lead_discovery.security.csrf import generate_csrf_token
from telegram_lead_discovery.storage.db import session_scope


def create_exports_router() -> APIRouter:
    router = APIRouter()

    @router.get("/exports/leads")
    async def exports_leads_get() -> HTMLResponse:
        return HTMLResponse(
            "Экспорт создаётся только через POST после preview",
            status_code=405,
        )

    @router.post("/exports/leads/preview")
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

    @router.post("/exports/leads")
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

    return router
