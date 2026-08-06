"""Run and progress routes for keyword discovery."""

from __future__ import annotations

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from telegram_lead_discovery.dashboard.discovery.constants import (
    VERSION_CONFLICT_MESSAGE,
)
from telegram_lead_discovery.dashboard.discovery.http_helpers import (
    _credentials_present,
    _csrf_or_403,
    _issue_csrf,
    _render_discovery,
    _safe_error,
)
from telegram_lead_discovery.dashboard.discovery.queries import (
    _apply_band_filter,
    _lifecycle_map,
    _order_opportunities,
)
from telegram_lead_discovery.dashboard.discovery.view_models import (
    _normalize_band_filter,
    _opportunity_view,
    _run_progress,
    _run_view,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunNotFoundError,
    KeywordRunStartError,
    KeywordRunVersionConflict,
    cancel_keyword_discovery_run,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    SourceOpportunitySnapshot,
)


def create_run_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["discovery"])

    def render(
        request: Request, name: str, context: dict[str, object]
    ) -> HTMLResponse:
        return _render_discovery(templates, request, name, context)

    @router.post("/discovery/runs")
    async def discovery_run_start(
        request: Request,
        csrf_token: str = Form(...),
        profile_id: int = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                result = await start_keyword_discovery_run(
                    session,
                    profile_id=profile_id,
                    credentials_present=_credentials_present(request),
                )
                run_id = result.run.id
        except KeywordRunStartError as exc:
            code = str(exc)
            status = 409 if code.startswith("active_keyword_run") else 422
            if code == "telegram_credentials_missing":
                status = 422
            return _safe_error(
                status_code=status,
                error_code=code.split(":", 1)[0],
                message=f"Запуск отклонён: {code}",
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="run_start_failed",
                message="Не удалось запустить разведку",
            )
        return RedirectResponse(url=f"/discovery/runs/{run_id}", status_code=303)

    @router.get("/discovery/runs/{run_id}", response_class=HTMLResponse)
    async def discovery_run_detail(request: Request, run_id: int) -> HTMLResponse:
        token = _issue_csrf(request)
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None or run.run_type != "keyword_scouting":
                return _safe_error(
                    status_code=404,
                    error_code="keyword_run_not_found",
                    message="Запуск разведки не найден",
                )
            progress = await _run_progress(session, run)
            view = _run_view(run, progress=progress)
            band_mode = _normalize_band_filter(None)
            result_rows = (
                await session.execute(
                    _order_opportunities(
                        _apply_band_filter(
                            select(SourceOpportunitySnapshot).where(
                                SourceOpportunitySnapshot.run_id == run_id
                            ),
                            band_mode,
                        )
                    ).limit(100)
                )
            ).scalars().all()
            lifecycle_map = await _lifecycle_map(session, result_rows)
            results = [
                _opportunity_view(
                    r,
                    lifecycle_state=(
                        lifecycle_map.get(r.source_id)
                        if r.source_id is not None
                        else None
                    ),
                )
                for r in result_rows
            ]
        return render(
            request,
            "discovery/run_detail.html",
            {
                "title": f"Разведка #{run_id}",
                "csrf_token": token,
                "run": view,
                "run_id": run_id,
                "results": results,
                "filters": {
                    "band": band_mode,
                    "source_type": None,
                    "linked_discussion_only": False,
                    "ecommerce_only": False,
                    "existing_source": None,
                    "review_state": None,
                },
            },
        )

    @router.get(
        "/discovery/runs/{run_id}/status-fragment", response_class=HTMLResponse
    )
    async def discovery_run_status_fragment(
        request: Request, run_id: int
    ) -> HTMLResponse:
        token = _issue_csrf(request)
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None or run.run_type != "keyword_scouting":
                return _safe_error(
                    status_code=404,
                    error_code="keyword_run_not_found",
                    message="Запуск разведки не найден",
                )
            progress = await _run_progress(session, run)
            view = _run_view(run, progress=progress)
        return render(
            request,
            "discovery/_run_status.html",
            {"title": f"Статус #{run_id}", "csrf_token": token, "run": view},
        )

    @router.get(
        "/discovery/runs/{run_id}/results-fragment", response_class=HTMLResponse
    )
    async def discovery_run_results_fragment(
        request: Request,
        run_id: int,
        band: str | None = Query(default=None),
        source_type: str | None = Query(default=None),
        linked_discussion_only: bool = Query(default=False),
        ecommerce_only: bool = Query(default=False),
        existing_source: str | None = Query(default=None),
        review_state: str | None = Query(default=None),
    ) -> HTMLResponse:
        token = _issue_csrf(request)
        async with session_scope() as session:
            run = await session.get(DiscoveryRun, run_id)
            if run is None or run.run_type != "keyword_scouting":
                return _safe_error(
                    status_code=404,
                    error_code="keyword_run_not_found",
                    message="Запуск разведки не найден",
                )
            stmt = select(SourceOpportunitySnapshot).where(
                SourceOpportunitySnapshot.run_id == run_id
            )
            band_mode = _normalize_band_filter(band)
            stmt = _apply_band_filter(stmt, band_mode)
            if source_type:
                stmt = stmt.where(SourceOpportunitySnapshot.source_type == source_type)
            if linked_discussion_only:
                stmt = stmt.where(
                    SourceOpportunitySnapshot.linked_parent_telegram_id.is_not(None)
                )
            if ecommerce_only:
                stmt = stmt.where(
                    SourceOpportunitySnapshot.ecommerce_qualified_count > 0
                )
            if existing_source == "existing":
                stmt = stmt.where(SourceOpportunitySnapshot.source_id.is_not(None))
            elif existing_source == "new":
                stmt = stmt.where(SourceOpportunitySnapshot.source_id.is_(None))
            if review_state:
                stmt = stmt.where(
                    SourceOpportunitySnapshot.review_state == review_state
                )
            stmt = _order_opportunities(stmt).limit(100)
            rows = (await session.execute(stmt)).scalars().all()
            lifecycle_map = await _lifecycle_map(session, rows)
            results = [
                _opportunity_view(
                    r,
                    lifecycle_state=(
                        lifecycle_map.get(r.source_id)
                        if r.source_id is not None
                        else None
                    ),
                )
                for r in rows
            ]
        return render(
            request,
            "discovery/_results.html",
            {
                "title": f"Результаты #{run_id}",
                "csrf_token": token,
                "run_id": run_id,
                "results": results,
                "filters": {
                    "band": band_mode,
                    "source_type": source_type,
                    "linked_discussion_only": linked_discussion_only,
                    "ecommerce_only": ecommerce_only,
                    "existing_source": existing_source,
                    "review_state": review_state,
                },
            },
        )

    @router.post("/discovery/runs/{run_id}/cancel")
    async def discovery_run_cancel(
        request: Request,
        run_id: int,
        csrf_token: str = Form(...),
        expected_version: int = Form(...),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        try:
            async with session_scope() as session:
                await cancel_keyword_discovery_run(
                    session,
                    run_id=run_id,
                    expected_version=expected_version,
                )
        except KeywordRunNotFoundError:
            return _safe_error(
                status_code=404,
                error_code="keyword_run_not_found",
                message="Запуск разведки не найден",
            )
        except KeywordRunVersionConflict:
            return HTMLResponse(VERSION_CONFLICT_MESSAGE, status_code=409)
        except KeywordRunStartError as exc:
            return _safe_error(
                status_code=422,
                error_code="run_not_cancellable",
                message=str(exc),
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="run_cancel_failed",
                message="Не удалось отменить запуск",
            )
        return RedirectResponse(url=f"/discovery/runs/{run_id}", status_code=303)

    return router
