"""Application runtime — startup order INF-003, CLI commands."""

from __future__ import annotations

import logging
from pathlib import Path

from telegram_lead_discovery.infrastructure.paths import (
    database_path,
    ensure_directories,
    lock_path,
)
from telegram_lead_discovery.infrastructure.process_lock import ProcessLock
from telegram_lead_discovery.observability.health import (
    HealthState,
    reset_health_registry,
)
from telegram_lead_discovery.observability.logging import StructuredLogger, configure_logging
from telegram_lead_discovery.security.bind_guard import assert_loopback_bind
from telegram_lead_discovery.security.preflight import run_security_preflight
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.storage.db import (
    init_engine,
    integrity_check_ok,
    pragma_probe,
    session_scope,
)
from telegram_lead_discovery.storage.jobs import recover_stale_jobs
from telegram_lead_discovery.storage.migrate import upgrade_head

logger = StructuredLogger("INF")


async def run_migrations() -> None:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    upgrade_head(path)
    await init_engine(path)


async def run_command(
    command: str,
    *,
    bind: str = "127.0.0.1",
    port: int = 8765,
    backup_path: Path | None = None,
) -> int | str:
    configure_logging()
    assert_loopback_bind(bind)
    ensure_directories()

    if command == "migrate":
        await run_migrations()
        logger.emit(level="info", event_code="migration.succeeded", result="ok")
        return 0

    if command == "integrity-check":
        await run_migrations()
        ok = await integrity_check_ok()
        logger.emit(
            level="info" if ok else "error",
            event_code="integrity.checked",
            result="ok" if ok else "failed",
        )
        return 0 if ok else "integrity_failed"

    if command == "start":
        registry = reset_health_registry()
        registry.set_component("runtime", HealthState.STARTING)

        lock = ProcessLock(lock_path())
        try:
            lock.acquire()
        except Exception as exc:
            if exc.__class__.__name__ == "AlreadyRunningError" or "already_running" in str(exc):
                return "already_running"
            raise

        preflight = run_security_preflight(bind=bind)
        if preflight.status == "blocked" and any("bind" in e for e in preflight.safe_errors):
            return "startup_failed"

        if preflight.status == "blocked":
            registry.set_component(
                "collector", HealthState.BLOCKED, reason_code="security_blocked"
            )
        else:
            registry.set_component("collector", HealthState.STOPPED, reason_code="deferred")

        try:
            await run_migrations()
            registry.migration_ok = True
        except Exception:
            registry.migration_ok = False
            from telegram_lead_discovery.observability.health import ReadinessState

            registry.readiness = ReadinessState.NOT_READY
            return "migration_failed"

        pragmas = await pragma_probe()
        logger.emit(level="info", event_code="sqlite.pragmas", fields=pragmas)

        if not await integrity_check_ok():
            registry.integrity_ok = False
            from telegram_lead_discovery.observability.health import ReadinessState

            registry.readiness = ReadinessState.NOT_READY
            logger.emit(level="critical", event_code="integrity_check_failed")
            return "integrity_failed"

        registry.integrity_ok = True
        registry.database_ok = True

        async with session_scope() as session:
            await seed_defaults(session)
            from telegram_lead_discovery.detection.seed import seed_ruleset_ru_mvp_1

            await seed_ruleset_ru_mvp_1(session)
            recovered = await recover_stale_jobs(session)
        logger.emit(
            level="info",
            event_code="jobs.recovered",
            result="ok",
            fields={"recovered": recovered},
        )
        registry.set_component("settings", HealthState.HEALTHY)
        registry.mark_ready()
        registry.set_component("runtime", HealthState.HEALTHY)
        registry.set_component("web", HealthState.HEALTHY)

        from telegram_lead_discovery.dashboard.app import create_app

        app = create_app()
        import uvicorn

        config = uvicorn.Config(
            app,
            host=bind,
            port=port,
            log_level="info",
            reload=False,
            workers=1,
            log_config=None,
        )
        server = uvicorn.Server(config)
        logging.getLogger("tld").setLevel(logging.INFO)
        try:
            await server.serve()
        finally:
            lock.release()
        return 0

    if command == "backup":
        from telegram_lead_discovery.infrastructure.backup import (
            create_online_backup,
            rotate_backups,
        )
        from telegram_lead_discovery.infrastructure.paths import resolve_app_paths
        from telegram_lead_discovery.storage.session import run_write

        await run_migrations()
        paths = resolve_app_paths()

        async def _backup(session):
            return await create_online_backup(session, paths=paths)

        manifest = await run_write(_backup)
        rotate_backups(paths)
        logger.emit(
            level="info",
            event_code="backup.succeeded",
            result="ok",
            fields={"path": manifest.path_ref, "checksum": manifest.database_checksum},
        )
        return 0

    if command == "restore":
        from telegram_lead_discovery.infrastructure.backup import restore_backup
        from telegram_lead_discovery.infrastructure.paths import resolve_app_paths
        from telegram_lead_discovery.infrastructure.process_lock import is_runtime_running

        if backup_path is None:
            logger.emit(
                level="error",
                event_code="restore.requires_explicit_path",
                result="failed",
            )
            return 1
        path = backup_path if isinstance(backup_path, Path) else Path(backup_path)
        if is_runtime_running():
            logger.emit(
                level="error",
                event_code="restore.runtime_running",
                result="failed",
            )
            return "restore_requires_stopped_runtime"
        restored = restore_backup(
            backup_path=path,
            paths=resolve_app_paths(),
            runtime_running=False,
        )
        logger.emit(
            level="info",
            event_code="restore.succeeded",
            result="ok",
            fields={"path": str(restored)},
        )
        return 0

    if command == "purge":
        from telegram_lead_discovery.infrastructure.maintenance import run_daily_purge
        from telegram_lead_discovery.infrastructure.paths import resolve_app_paths
        from telegram_lead_discovery.storage.session import run_write

        await run_migrations()
        paths = resolve_app_paths()

        async def _purge(session):
            return await run_daily_purge(session, paths=paths)

        result = await run_write(_purge)
        logger.emit(
            level="info",
            event_code="purge.succeeded",
            result="ok",
            fields={
                "exports_tmp_deleted": result.exports_tmp_deleted,
                "terminal_outbox_deleted": result.terminal_outbox_deleted,
                "terminal_deliveries_deleted": result.terminal_deliveries_deleted,
                "duration_ms": result.duration_ms,
            },
        )
        return 0

    return 1
