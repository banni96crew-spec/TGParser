"""Start-keyword-run HTTP command (UI-028 / SRC-019)."""

from __future__ import annotations

from fastapi.responses import HTMLResponse, RedirectResponse

from telegram_lead_discovery.dashboard.discovery.http_helpers import (
    _lines,
    _safe_error,
)
from telegram_lead_discovery.source_discovery.keyword_run import (
    KeywordRunStartError,
    start_keyword_discovery_run,
)
from telegram_lead_discovery.storage.db import session_scope


async def execute_start_keyword_run(
    *,
    profile_id: int,
    seed_refs_text: str,
    expected_version: int | None,
    credentials_present: bool,
) -> HTMLResponse:
    try:
        async with session_scope() as session:
            result = await start_keyword_discovery_run(
                session,
                profile_id=profile_id,
                credentials_present=credentials_present,
                seed_refs=_lines(seed_refs_text),
                expected_profile_version=expected_version,
            )
            run_id = result.run.id
    except KeywordRunStartError as exc:
        code = str(exc)
        status = 422
        if code.startswith(
            ("active_keyword_run", "telegram_discovery_busy", "profile_version_conflict")
        ):
            status = 409
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
