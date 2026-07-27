"""Keyword discovery UI routes (UI-017/018, plan §14.2 / §14.7).

CSRF on every POST; success redirects use 303; optimistic ``expected_version``
on profile version, run cancel, promote, and dismiss. No Stars / paid fields.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from telegram_lead_discovery.observability.health import get_health_registry
from telegram_lead_discovery.security.csrf import generate_csrf_token, validate_csrf_token
from telegram_lead_discovery.security.secrets import read_secret_presence
from telegram_lead_discovery.source_discovery.keyword_profiles import (
    MAX_DIRECTORY_QUERIES,
    MAX_POST_QUERIES,
    ProfileValidationError,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunNotFoundError,
    KeywordRunStartError,
    KeywordRunVersionConflict,
    cancel_keyword_discovery_run,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.source_discovery.keyword_search import (
    POOL_EXHAUSTED_REASON_CODES,
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
from telegram_lead_discovery.source_discovery.promotion import (
    OpportunityNotFoundError,
    OpportunityReviewStateError,
    OpportunityVersionConflict,
    dismiss_opportunity,
    promote_opportunity_to_candidate,
    reconsider_dismiss_suppress,
)
from telegram_lead_discovery.storage.db import session_scope
from telegram_lead_discovery.storage.dismissed_suppress import get_suppress_by_canonical_key
from telegram_lead_discovery.storage.models import (
    DiscoveryRun,
    DiscoveryRunQuery,
    DismissedKeywordSource,
    KeywordDiscoveryProfile,
    SourceAlias,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    TelegramSource,
)

ZERO_STARS_LABEL = "Максимальная стоимость: 0 Stars"
VERSION_CONFLICT_MESSAGE = "Данные изменились. Обновите страницу"
EVIDENCE_RETENTION_MESSAGE = "Доказательства очищены по retention policy"
CONFIRM_RECONSIDER_SUPPRESS = "RECONSIDER_SUPPRESS"

_TERMINAL_QUERY_STATES = frozenset(
    {
        "succeeded",
        "failed",
        "cancelled",
        "quota_skipped",
        "budget_skipped",
    }
)
_ACTIVE_RUN_STATES = frozenset(
    {"queued", "running", "retry_wait_flood", "cancelling"}
)
_SEED_QUERY_KINDS = frozenset({"global_message", "directory", "public_posts"})
# Default queue: review + promising (plan moderate/strong aliases). weak is opt-in.
_DEFAULT_BANDS = frozenset({"review", "promising"})
_BAND_FILTER_DEFAULT = "default"

_POOL_REASON_BY_CODE = {v: k for k, v in POOL_EXHAUSTED_REASON_CODES.items()}
_FUNNEL_KEYS = (
    "acquired_total",
    "canonicalized_total",
    "registry_suppressed",
    "dismissed_suppressed",
    "cooldown_suppressed",
    "suppressed_total",
    "qualified_total",
    "presented_total",
    "novel_presented_total",
    "duplicate_in_run",
)


def _csrf_or_403(request: Request, csrf_token: str) -> HTMLResponse | None:
    expected = request.session.get("csrf_token")
    if not validate_csrf_token(expected, csrf_token):
        return HTMLResponse("CSRF отклонён", status_code=403)
    return None


def _issue_csrf(request: Request) -> str:
    token = generate_csrf_token()
    request.session["csrf_token"] = token
    return token


def _safe_error(
    *,
    status_code: int,
    error_code: str,
    message: str,
    correlation_id: str | None = None,
) -> HTMLResponse:
    cid = correlation_id or str(uuid.uuid4())
    body = f"{message} (код: {error_code}; correlation_id: {cid})"
    return HTMLResponse(body, status_code=status_code)


def _lines(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _credentials_present(request: Request) -> bool:
    flag = getattr(request.app.state, "telegram_credentials_present", None)
    if flag is not None:
        return bool(flag)
    presence = read_secret_presence()
    return bool(presence.tg_api_id and presence.tg_api_hash)


def _telegram_connection_state(request: Request) -> str:
    if not _credentials_present(request):
        return "credentials_missing"
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None:
        return "disconnected"
    return "connected"


async def _quota_summary(request: Request) -> dict[str, Any]:
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None or not hasattr(gateway, "check_public_post_search_quota"):
        return {
            "available": False,
            "free_slot_available": None,
            "premium_required": None,
            "label": "квота недоступна (нет gateway)",
        }
    try:
        quota = await gateway.check_public_post_search_quota("нужен разработчик сайта")
        return {
            "available": True,
            "free_slot_available": quota.free_slot_available,
            "premium_required": quota.premium_required,
            "label": (
                "бесплатный слот доступен"
                if quota.free_slot_available
                else "бесплатный слот исчерпан"
            ),
        }
    except Exception:  # noqa: BLE001 — UI must not expose gateway internals
        return {
            "available": False,
            "free_slot_available": None,
            "premium_required": None,
            "label": "квота временно недоступна",
        }


def _loads_json_obj(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _run_view(
    run: DiscoveryRun,
    *,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counters = _loads_json_obj(run.counters_json, {})
    if not isinstance(counters, dict):
        counters = {}
    prog = progress or {}
    pool_exhausted = bool(int(counters.get("pool_exhausted") or 0))
    reason_code = counters.get("pool_exhausted_reason_code")
    pool_reason = None
    if isinstance(reason_code, int):
        pool_reason = _POOL_REASON_BY_CODE.get(reason_code, f"code_{reason_code}")
    novelty_bp = int(counters.get("novelty_ratio_bp") or 0)
    funnel = {key: int(counters.get(key) or 0) for key in _FUNNEL_KEYS}
    # Aggregate suppressed for UI-020 "suppressed" line when total missing.
    if funnel["suppressed_total"] == 0:
        funnel["suppressed_total"] = (
            funnel["registry_suppressed"]
            + funnel["dismissed_suppressed"]
            + funnel["cooldown_suppressed"]
            + funnel["duplicate_in_run"]
        )
    return {
        "id": run.id,
        "state": run.state,
        "phase": run.phase,
        "version": run.version,
        "search_mode": run.search_mode,
        "last_error_code": run.last_error_code,
        "counters": counters,
        "funnel": funnel,
        "pool_exhausted": pool_exhausted,
        "pool_exhausted_reason": pool_reason,
        "novelty_ratio": novelty_bp / 10000.0,
        "novelty_ratio_bp": novelty_bp,
        "novelty_ratio_pct": f"{novelty_bp / 100:.2f}%",
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "queries_total": int(prog.get("queries_total", 0)),
        "queries_done": int(prog.get("queries_done", 0)),
        "progress_pct": int(prog.get("progress_pct", 0)),
        "seed_hits": int(prog.get("seed_hits", 0)),
        "verified_sources": int(prog.get("verified_sources", 0)),
        "flood_wait_until": prog.get("flood_wait_until"),
        "is_active": bool(prog.get("is_active", run.state in _ACTIVE_RUN_STATES)),
        "is_loading": run.state in _ACTIVE_RUN_STATES,
        "is_degraded": run.state == "retry_wait_flood" or bool(run.last_error_code),
        "is_error": run.state == "failed",
        "is_empty": (
            run.state not in _ACTIVE_RUN_STATES
            and int(counters.get("presented_total") or 0) == 0
            and int(counters.get("unique_sources") or 0) == 0
        ),
    }


async def _run_progress(session: Any, run: DiscoveryRun) -> dict[str, Any]:
    queries = (
        await session.execute(
            select(DiscoveryRunQuery).where(DiscoveryRunQuery.run_id == run.id)
        )
    ).scalars().all()
    total = len(queries)
    done = sum(1 for q in queries if q.state in _TERMINAL_QUERY_STATES)
    seed_hits = sum(
        int(q.result_count or 0) for q in queries if q.query_kind in _SEED_QUERY_KINDS
    )
    verified = sum(
        1
        for q in queries
        if q.query_kind == "source_verification" and q.state == "succeeded"
    )
    flood_until = None
    for q in queries:
        if q.state == "retry_wait" and q.available_at is not None:
            if flood_until is None or q.available_at > flood_until:
                flood_until = q.available_at
    return {
        "queries_total": total,
        "queries_done": done,
        "progress_pct": int(100 * done / total) if total else 0,
        "seed_hits": seed_hits,
        "verified_sources": verified,
        "flood_wait_until": flood_until,
        "is_active": run.state in _ACTIVE_RUN_STATES,
    }


def _rank_reason(view: dict[str, Any]) -> str:
    components = view.get("score_components") or {}
    ordered = (
        "qualified",
        "regularity",
        "ecommerce",
        "recency",
        "noise_penalty",
    )
    parts = [f"{key}={components.get(key, 0)}" for key in ordered]
    eligibility = components.get("eligibility_reasons") or components.get("reason_codes") or []
    if isinstance(eligibility, list) and eligibility:
        parts.append("reasons=" + ",".join(str(r) for r in eligibility))
    return (
        f"Выше других по score {view.get('score', 0)} "
        f"(band={view.get('band', 'weak')}; {', '.join(parts)})"
    )


def _eligibility_reasons(components: dict[str, Any]) -> list[str]:
    raw = components.get("eligibility_reasons") or components.get("reason_codes") or []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _normalize_band_filter(band: str | None) -> str:
    """Map query param to filter mode. Missing/empty → default (hide weak)."""
    if band is None or band == "" or band == _BAND_FILTER_DEFAULT:
        return _BAND_FILTER_DEFAULT
    if band == "all":
        return "all"
    if band in ("promising", "review", "weak"):
        return band
    return _BAND_FILTER_DEFAULT


def _apply_band_filter(stmt: Any, band_mode: str) -> Any:
    if band_mode == "all":
        return stmt
    if band_mode == _BAND_FILTER_DEFAULT:
        return stmt.where(SourceOpportunitySnapshot.band.in_(tuple(_DEFAULT_BANDS)))
    return stmt.where(SourceOpportunitySnapshot.band == band_mode)


def _sampling_label(sample_message_count: int) -> str:
    if sample_message_count <= 0:
        return "Недостаточный sample (0 сообщений)"
    return f"Sample: {sample_message_count} сообщений"


def _opportunity_view(
    row: SourceOpportunitySnapshot,
    *,
    lifecycle_state: str | None = None,
    aliases: list[str] | None = None,
    suppress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = _loads_json_obj(row.score_components_json, {})
    channels = _loads_json_obj(row.discovery_channels_json, [])
    if not isinstance(components, dict):
        components = {}
    if not isinstance(channels, list):
        channels = []
    existing = row.source_id is not None
    lifecycle = lifecycle_state or ("existing" if existing else "new")
    noise = components.get("noise_penalty", row.excluded_count)
    identity = {
        "telegram_id": row.source_telegram_id,
        "username": row.username,
        "title": row.title,
        "source_type": row.source_type,
        "public_url": row.public_url,
        "canonical_key": (
            f"peer:{row.source_telegram_id}"
            if row.source_telegram_id is not None
            else (
                f"username:{str(row.username).casefold()}"
                if row.username
                else None
            )
        ),
    }
    alias_list = list(aliases or [])
    if row.username and row.username not in alias_list:
        alias_list = [row.username, *alias_list]
    view = {
        "id": row.id,
        "run_id": row.run_id,
        "source_telegram_id": row.source_telegram_id,
        "username": row.username,
        "title": row.title,
        "source_type": row.source_type,
        "public_url": row.public_url,
        "linked_parent_telegram_id": row.linked_parent_telegram_id,
        "is_linked_discussion": row.linked_parent_telegram_id is not None,
        "qualified_count": row.qualified_count,
        "excluded_count": row.excluded_count,
        "active_week_count": row.active_week_count,
        "ecommerce_qualified_count": row.ecommerce_qualified_count,
        "last_qualified_at": row.last_qualified_at,
        "sample_message_count": row.sample_message_count,
        "sampling_label": _sampling_label(row.sample_message_count),
        "score": row.score,
        "band": row.band,
        "score_components": components,
        "eligibility_reasons": _eligibility_reasons(components),
        "discovery_channels": channels,
        "provenance": channels,
        "identity": identity,
        "aliases": alias_list,
        "evidence_counts": {
            "qualified": row.qualified_count,
            "excluded": row.excluded_count,
            "sample": row.sample_message_count,
            "active_weeks": row.active_week_count,
            "ecommerce_qualified": row.ecommerce_qualified_count,
        },
        "review_state": row.review_state,
        "promoted_source_id": row.promoted_source_id,
        "source_id": row.source_id,
        "existing_source": existing,
        "lifecycle_state": lifecycle,
        "noise": noise,
        "version": row.version,
        "dismiss_reason": row.dismiss_reason,
        "suppress": suppress,
    }
    view["rank_reason"] = _rank_reason(view)
    return view


def _evidence_item(row: SourceDiscoveryEvidence) -> dict[str, Any]:
    ordinals = _loads_json_obj(row.matched_query_ordinals_json, [])
    profiles = _loads_json_obj(row.service_profiles_json, [])
    return {
        "excerpt": row.excerpt or "",
        "permalink": row.permalink,
        "category": row.detection_category,
        "service_profiles": profiles if isinstance(profiles, list) else [],
        "matched_query_ordinals": ordinals if isinstance(ordinals, list) else [],
        "is_qualified": row.is_qualified,
        "published_at": row.published_at,
    }


async def _lifecycle_map(
    session: Any, rows: list[SourceOpportunitySnapshot]
) -> dict[int, str]:
    source_ids = {r.source_id for r in rows if r.source_id is not None}
    if not source_ids:
        return {}
    sources = (
        await session.execute(
            select(TelegramSource).where(TelegramSource.id.in_(source_ids))
        )
    ).scalars().all()
    return {s.id: s.lifecycle_state for s in sources}


async def _aliases_for_source(
    session: Any, source_id: int | None
) -> list[str]:
    if source_id is None:
        return []
    rows = (
        await session.execute(
            select(SourceAlias)
            .where(SourceAlias.source_id == source_id)
            .order_by(SourceAlias.id.asc())
        )
    ).scalars().all()
    return [r.normalized_username for r in rows]


async def _suppress_for_opportunity(
    session: Any, row: SourceOpportunitySnapshot
) -> dict[str, Any] | None:
    key = (
        f"peer:{row.source_telegram_id}"
        if row.source_telegram_id is not None
        else (
            f"username:{str(row.username).casefold()}" if row.username else None
        )
    )
    suppress_row: DismissedKeywordSource | None = None
    if key:
        suppress_row = await get_suppress_by_canonical_key(session, canonical_key=key)
    if suppress_row is None and row.source_telegram_id is not None:
        suppress_row = (
            await session.execute(
                select(DismissedKeywordSource).where(
                    DismissedKeywordSource.source_telegram_id == row.source_telegram_id
                )
            )
        ).scalar_one_or_none()
    if suppress_row is None:
        return None
    aliases = _loads_json_obj(suppress_row.aliases_json, [])
    if not isinstance(aliases, list):
        aliases = []
    return {
        "id": suppress_row.id,
        "canonical_key": suppress_row.canonical_key,
        "version": suppress_row.version,
        "dismiss_reason": suppress_row.dismiss_reason,
        "aliases": [str(a) for a in aliases],
    }


def create_discovery_router(templates: Jinja2Templates) -> APIRouter:
    """Build discovery router bound to the dashboard Jinja environment."""
    router = APIRouter(tags=["discovery"])

    def render(
        request: Request, name: str, context: dict[str, object]
    ) -> HTMLResponse:
        payload = {
            **context,
            "active_nav": "discovery",
            "zero_stars_label": ZERO_STARS_LABEL,
        }
        return templates.TemplateResponse(request, name, payload)

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
                    "window_days": 30,
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
                    _apply_band_filter(
                        select(SourceOpportunitySnapshot).where(
                            SourceOpportunitySnapshot.run_id == run_id
                        ),
                        band_mode,
                    )
                    .order_by(
                        SourceOpportunitySnapshot.score.desc(),
                        SourceOpportunitySnapshot.id.asc(),
                    )
                    .limit(100)
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
            stmt = stmt.order_by(
                SourceOpportunitySnapshot.score.desc(),
                SourceOpportunitySnapshot.id.asc(),
            ).limit(100)
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
                    .limit(5)
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


__all__ = [
    "CONFIRM_RECONSIDER_SUPPRESS",
    "EVIDENCE_RETENTION_MESSAGE",
    "VERSION_CONFLICT_MESSAGE",
    "ZERO_STARS_LABEL",
    "create_discovery_router",
]
