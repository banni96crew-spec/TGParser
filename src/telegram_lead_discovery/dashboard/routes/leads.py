"""Lead inbox, detail, and status routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from telegram_lead_discovery.dashboard.leads import (
    ALLOWED_STATUSES,
    get_active_rule_pin,
    list_inbox_leads,
    update_lead_status,
)
from telegram_lead_discovery.dashboard.view_helpers import (
    _csrf_or_403,
    _lead_rows,
    _rule_pin_dict,
    _template,
)
from telegram_lead_discovery.security.csrf import generate_csrf_token
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    Lead,
    LeadScore,
    LeadScoreComponent,
    RuleSetVersion,
    TelegramMessage,
    TelegramSource,
)


def create_leads_router() -> APIRouter:
    router = APIRouter()

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

    @router.get("/", response_class=HTMLResponse)
    async def home(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return _template(request, "home.html", ctx)

    @router.get("/inbox/fragment", response_class=HTMLResponse)
    async def inbox_fragment(
        request: Request,
        band: str | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None),
    ) -> HTMLResponse:
        ctx = await _inbox_context(request, band=band, cursor=cursor, limit=limit)
        return _template(request, "inbox_fragment.html", ctx)

    @router.get("/leads/{lead_id}", response_class=HTMLResponse)
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

    @router.post("/leads/{lead_id}/status")
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

    return router
