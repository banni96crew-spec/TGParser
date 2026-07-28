"""Opportunity-result routes for keyword discovery."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from telegram_lead_discovery.dashboard.discovery.constants import (
    CONFIRM_RECONSIDER_SUPPRESS,
    EVIDENCE_RETENTION_MESSAGE,
    VERSION_CONFLICT_MESSAGE,
)
from telegram_lead_discovery.dashboard.discovery.http_helpers import (
    _csrf_or_403,
    _issue_csrf,
    _render_discovery,
    _safe_error,
)
from telegram_lead_discovery.dashboard.discovery.queries import (
    _aliases_for_source,
    _suppress_for_opportunity,
)
from telegram_lead_discovery.dashboard.discovery.view_models import (
    _evidence_item,
    _opportunity_view,
)
from telegram_lead_discovery.source_discovery.promotion import (
    OpportunityNotFoundError,
    OpportunityReviewStateError,
    OpportunityVersionConflict,
    dismiss_opportunity,
    promote_opportunity_to_candidate,
    reconsider_dismiss_suppress,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)


def create_result_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["discovery"])

    def render(
        request: Request, name: str, context: dict[str, object]
    ) -> HTMLResponse:
        return _render_discovery(templates, request, name, context)

    @router.get("/discovery/results/{result_id}", response_class=HTMLResponse)
    async def discovery_result_detail(
        request: Request, result_id: int
    ) -> HTMLResponse:
        token = _issue_csrf(request)
        async with session_scope() as session:
            row = await session.get(SourceOpportunitySnapshot, result_id)
            if row is None:
                return _safe_error(
                    status_code=404,
                    error_code="opportunity_not_found",
                    message="Результат не найден",
                )
            evidence_rows = (
                await session.execute(
                    select(SourceDiscoveryEvidence)
                    .where(
                        SourceDiscoveryEvidence.run_id == row.run_id,
                        SourceDiscoveryEvidence.source_telegram_id
                        == row.source_telegram_id,
                    )
                    .order_by(SourceDiscoveryEvidence.id.asc())
                    .limit(20)
                )
            ).scalars().all()
            evidence_items = [_evidence_item(e) for e in evidence_rows]
            excerpts = [item["excerpt"] for item in evidence_items if item["excerpt"]]
            evidence_purged = bool(evidence_rows) and not excerpts
            lifecycle = None
            if row.source_id is not None:
                src = await session.get(TelegramSource, row.source_id)
                lifecycle = src.lifecycle_state if src is not None else None
            aliases = await _aliases_for_source(session, row.source_id)
            suppress = await _suppress_for_opportunity(session, row)
            view = _opportunity_view(
                row,
                lifecycle_state=lifecycle,
                aliases=aliases,
                suppress=suppress,
            )
            categories = sorted(
                {item["category"] for item in evidence_items if item["category"]}
            )
            service_profiles: list[str] = []
            seen_profiles: set[str] = set()
            matched_ordinals: set[int] = set()
            for item in evidence_items:
                for profile in item["service_profiles"]:
                    key = str(profile)
                    if key not in seen_profiles:
                        seen_profiles.add(key)
                        service_profiles.append(key)
                for ordinal in item["matched_query_ordinals"]:
                    try:
                        matched_ordinals.add(int(ordinal))
                    except (TypeError, ValueError):
                        continue
        return render(
            request,
            "discovery/result_detail.html",
            {
                "title": f"Результат #{result_id}",
                "csrf_token": token,
                "result": view,
                "evidence_items": evidence_items,
                "evidence_excerpts": excerpts,
                "evidence_message": (
                    EVIDENCE_RETENTION_MESSAGE if evidence_purged else None
                ),
                "categories": categories,
                "service_profiles": service_profiles,
                "matched_query_ordinals": sorted(matched_ordinals),
                "confirm_reconsider_suppress": CONFIRM_RECONSIDER_SUPPRESS,
            },
        )

    @router.post("/discovery/results/{result_id}/promote")
    async def discovery_result_promote(
        request: Request,
        result_id: int,
        csrf_token: str = Form(...),
        expected_version: int = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                await promote_opportunity_to_candidate(
                    session,
                    opportunity_id=result_id,
                    version=expected_version,
                )
        except OpportunityNotFoundError:
            return _safe_error(
                status_code=404,
                error_code="opportunity_not_found",
                message="Результат не найден",
            )
        except OpportunityVersionConflict:
            return HTMLResponse(VERSION_CONFLICT_MESSAGE, status_code=409)
        except OpportunityReviewStateError as exc:
            return _safe_error(
                status_code=422,
                error_code="opportunity_review_state",
                message=str(exc),
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="promote_failed",
                message="Не удалось добавить в кандидаты",
            )
        return RedirectResponse(
            url=f"/discovery/results/{result_id}", status_code=303
        )

    @router.post("/discovery/results/{result_id}/dismiss")
    async def discovery_result_dismiss(
        request: Request,
        result_id: int,
        csrf_token: str = Form(...),
        expected_version: int = Form(...),
        reason: str = Form(default="hidden_by_operator"),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                await dismiss_opportunity(
                    session,
                    opportunity_id=result_id,
                    version=expected_version,
                    reason=(reason or "hidden_by_operator").strip()[:512],
                )
        except OpportunityNotFoundError:
            return _safe_error(
                status_code=404,
                error_code="opportunity_not_found",
                message="Результат не найден",
            )
        except OpportunityVersionConflict:
            return HTMLResponse(VERSION_CONFLICT_MESSAGE, status_code=409)
        except OpportunityReviewStateError as exc:
            return _safe_error(
                status_code=422,
                error_code="opportunity_review_state",
                message=str(exc),
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="dismiss_failed",
                message="Не удалось скрыть результат",
            )
        return RedirectResponse(
            url=f"/discovery/results/{result_id}", status_code=303
        )

    @router.post("/discovery/results/{result_id}/reconsider-suppress")
    async def discovery_result_reconsider_suppress(
        request: Request,
        result_id: int,
        csrf_token: str = Form(...),
        confirm: str = Form(default=""),
        note: str = Form(default=""),
        expected_version: int | None = Form(default=None),
        suppress_id: int | None = Form(default=None),
    ) -> HTMLResponse:
        """UI-019: ReconsiderDismissSuppress — CSRF + explicit confirmation required."""
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        if confirm.strip() != CONFIRM_RECONSIDER_SUPPRESS:
            return _safe_error(
                status_code=400,
                error_code="confirm_required",
                message=(
                    "Требуется подтверждение: введите "
                    f"{CONFIRM_RECONSIDER_SUPPRESS}"
                ),
            )
        try:
            async with session_scope() as session:
                row = await session.get(SourceOpportunitySnapshot, result_id)
                if row is None:
                    return _safe_error(
                        status_code=404,
                        error_code="opportunity_not_found",
                        message="Результат не найден",
                    )
                suppress = await _suppress_for_opportunity(session, row)
                sid = suppress_id or (suppress["id"] if suppress else None)
                canonical = suppress["canonical_key"] if suppress else None
                if sid is None and not canonical:
                    return _safe_error(
                        status_code=404,
                        error_code="suppress_not_found",
                        message="Запись suppress не найдена",
                    )
                version = expected_version
                if version is None and suppress is not None:
                    version = int(suppress["version"])
                await reconsider_dismiss_suppress(
                    session,
                    suppress_id=sid,
                    canonical_key=canonical,
                    note=(note or "").strip()[:1000],
                    version=version,
                )
        except ValueError as exc:
            code = str(exc)
            if code.startswith("suppress_version_conflict"):
                return HTMLResponse(VERSION_CONFLICT_MESSAGE, status_code=409)
            return _safe_error(
                status_code=422,
                error_code="reconsider_suppress_failed",
                message=code,
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="reconsider_suppress_failed",
                message="Не удалось снять suppress",
            )
        return RedirectResponse(
            url=f"/discovery/results/{result_id}", status_code=303
        )

    return router
