"""Profile-management routes for keyword discovery."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
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
    _lines,
    _render_discovery,
    _safe_error,
    _telegram_connection_state,
)
from telegram_lead_discovery.dashboard.discovery.view_models import (
    _quota_summary,
    _run_view,
)
from telegram_lead_discovery.observability.health import get_health_registry
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    MAX_DIRECTORY_QUERIES,
    MAX_POST_QUERIES,
    ProfileValidationError,
)
from telegram_lead_discovery.source_discovery.profile_service import (
    ProfileNotFoundError,
    ProfileVersionConflict,
    create_keyword_discovery_profile,
    create_keyword_discovery_profile_version,
    ensure_seed_keyword_profile,
    get_current_profile_version,
    get_profile,
    version_as_normalized,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    KeywordDiscoveryProfile,
)


def create_profile_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["discovery"])

    def render(
        request: Request, name: str, context: dict[str, object]
    ) -> HTMLResponse:
        return _render_discovery(templates, request, name, context)

    @router.get("/discovery", response_class=HTMLResponse)
    async def discovery_index(request: Request) -> HTMLResponse:
        token = _issue_csrf(request)
        async with session_scope() as session:
            seed = await ensure_seed_keyword_profile(session)
            profiles = (
                await session.execute(
                    select(KeywordDiscoveryProfile)
                    .where(KeywordDiscoveryProfile.state == "active")
                    .order_by(KeywordDiscoveryProfile.name.asc())
                )
            ).scalars().all()
            version_row = await get_current_profile_version(session, seed.profile.id)
            normalized = version_as_normalized(version_row)
            runs = (
                await session.execute(
                    select(DiscoveryRun)
                    .where(DiscoveryRun.run_type == "keyword_scouting")
                    .order_by(DiscoveryRun.id.desc())
                    .limit(20)
                )
            ).scalars().all()

        registry = get_health_registry()
        discovery_health = registry.components.get("discovery")
        quota = await _quota_summary(request)
        return render(
            request,
            "discovery/index.html",
            {
                "title": "Разведка источников",
                "csrf_token": token,
                "active_profile": seed.profile,
                "active_version": version_row,
                "normalized": normalized,
                "profiles": profiles,
                "runs": [_run_view(r) for r in runs],
                "limits": {
                    "max_post_queries": MAX_POST_QUERIES,
                    "max_directory_queries": MAX_DIRECTORY_QUERIES,
                    "window_days": 14,
                },
                "telegram_connection_state": _telegram_connection_state(request),
                "credentials_present": _credentials_present(request),
                "quota": quota,
                "discovery_health": (
                    discovery_health.state.value if discovery_health else "unknown"
                ),
            },
        )

    @router.get("/discovery/profiles/new", response_class=HTMLResponse)
    async def discovery_profile_new(request: Request) -> HTMLResponse:
        token = _issue_csrf(request)
        return render(
            request,
            "discovery/profile_form.html",
            {
                "title": "Новый профиль разведки",
                "csrf_token": token,
                "mode": "create",
                "profile": None,
                "version": None,
                "post_queries_text": "",
                "directory_queries_text": "",
                "additional_exclusions_text": "",
                "source_scope": "all",
                "required_service_profiles_text": "",
                "expected_version": None,
            },
        )

    @router.post("/discovery/profiles")
    async def discovery_profile_create(
        request: Request,
        csrf_token: str = Form(...),
        name: str = Form(...),
        post_queries: str = Form(...),
        directory_queries: str = Form(default=""),
        additional_exclusions: str = Form(default=""),
        source_scope: str = Form(default="all"),
        required_service_profiles: str = Form(default=""),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        scope = source_scope if source_scope in {"groups", "channels", "all"} else "all"
        try:
            async with session_scope() as session:
                created = await create_keyword_discovery_profile(
                    session,
                    name=name,
                    post_queries=_lines(post_queries),
                    directory_queries=_lines(directory_queries),
                    additional_exclusions=_lines(additional_exclusions),
                    source_scope=scope,  # type: ignore[arg-type]
                    required_service_profiles=_lines(required_service_profiles),
                )
                profile_id = created.profile.id
        except ProfileValidationError as exc:
            return _safe_error(
                status_code=422,
                error_code="profile_validation_error",
                message=str(exc),
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="profile_create_failed",
                message="Не удалось создать профиль",
            )
        return RedirectResponse(url=f"/discovery/profiles/{profile_id}", status_code=303)

    @router.get("/discovery/profiles/{profile_id}", response_class=HTMLResponse)
    async def discovery_profile_detail(
        request: Request, profile_id: int
    ) -> HTMLResponse:
        token = _issue_csrf(request)
        try:
            async with session_scope() as session:
                profile = await get_profile(session, profile_id)
                version_row = await get_current_profile_version(session, profile_id)
                normalized = version_as_normalized(version_row)
        except ProfileNotFoundError:
            return _safe_error(
                status_code=404,
                error_code="profile_not_found",
                message="Профиль не найден",
            )
        except ProfileValidationError as exc:
            return _safe_error(
                status_code=422,
                error_code="profile_invalid",
                message=str(exc),
            )
        return render(
            request,
            "discovery/profile_form.html",
            {
                "title": f"Профиль {profile.name}",
                "csrf_token": token,
                "mode": "edit",
                "profile": profile,
                "version": version_row,
                "post_queries_text": "\n".join(normalized.post_queries),
                "directory_queries_text": "\n".join(normalized.directory_queries),
                "additional_exclusions_text": "\n".join(normalized.additional_exclusions),
                "source_scope": normalized.source_scope,
                "required_service_profiles_text": "\n".join(
                    normalized.required_service_profiles
                ),
                "expected_version": profile.current_version,
            },
        )

    @router.post("/discovery/profiles/{profile_id}/versions")
    async def discovery_profile_version_create(
        request: Request,
        profile_id: int,
        csrf_token: str = Form(...),
        expected_version: int = Form(...),
        post_queries: str = Form(...),
        directory_queries: str = Form(default=""),
        additional_exclusions: str = Form(default=""),
        source_scope: str = Form(default="all"),
        required_service_profiles: str = Form(default=""),
    ) -> HTMLResponse:
        rejected = _csrf_or_403(request, csrf_token)
        if rejected is not None:
            return rejected
        scope = source_scope if source_scope in {"groups", "channels", "all"} else "all"
        try:
            async with session_scope() as session:
                await create_keyword_discovery_profile_version(
                    session,
                    profile_id=profile_id,
                    expected_version=expected_version,
                    post_queries=_lines(post_queries),
                    directory_queries=_lines(directory_queries),
                    additional_exclusions=_lines(additional_exclusions),
                    source_scope=scope,  # type: ignore[arg-type]
                    required_service_profiles=_lines(required_service_profiles),
                )
        except ProfileNotFoundError:
            return _safe_error(
                status_code=404,
                error_code="profile_not_found",
                message="Профиль не найден",
            )
        except ProfileVersionConflict:
            return HTMLResponse(VERSION_CONFLICT_MESSAGE, status_code=409)
        except ProfileValidationError as exc:
            return _safe_error(
                status_code=422,
                error_code="profile_validation_error",
                message=str(exc),
            )
        except Exception:  # noqa: BLE001
            return _safe_error(
                status_code=500,
                error_code="profile_version_failed",
                message="Не удалось создать версию профиля",
            )
        return RedirectResponse(
            url=f"/discovery/profiles/{profile_id}", status_code=303
        )

    return router
