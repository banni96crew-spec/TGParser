"""Application runtime — startup order INF-003, CLI commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telegram_lead_discovery.collector.ports import TelegramGateway
from telegram_lead_discovery.infrastructure.paths import (
    database_path,
    ensure_directories,
    lock_path,
)
from telegram_lead_discovery.infrastructure.process_lock import ProcessLock
from telegram_lead_discovery.observability.discovery import (
    mark_discovery_blocked,
    mark_discovery_healthy,
    mark_discovery_stopped,
)
from telegram_lead_discovery.observability.health import (
    HealthRegistry,
    HealthState,
    reset_health_registry,
)
from telegram_lead_discovery.observability.logging import StructuredLogger, configure_logging
from telegram_lead_discovery.security.bind_guard import assert_loopback_bind
from telegram_lead_discovery.security.preflight import run_security_preflight
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.worker import KeywordDiscoveryClaimLoop
from telegram_lead_discovery.storage.db import (
    init_engine,
    integrity_check_ok,
    pragma_probe,
    session_scope,
)
from telegram_lead_discovery.storage.jobs import recover_stale_jobs
from telegram_lead_discovery.storage.migrate import upgrade_head

logger = StructuredLogger("INF")

START_DISABLED_TELEGRAM_CREDENTIALS_MISSING = "telegram_credentials_missing"


@dataclass
class RuntimeCoordinator:
    """Owns shared TelegramGateway + keyword discovery claim loop (INF-021).

    One gateway instance is shared with discovery worker, dashboard approval
    handlers, and (later) the collector worker. Long keyword search must not
    use FastAPI BackgroundTasks.
    """

    gateway: TelegramGateway | None = None
    credentials_present: bool = False
    start_disabled_reason: str | None = None
    discovery_loop: KeywordDiscoveryClaimLoop | None = field(default=None, repr=False)
    _started: bool = field(default=False, repr=False)

    @property
    def worker_running(self) -> bool:
        loop = self.discovery_loop
        return loop is not None and loop.task is not None and not loop.task.done()

    async def start(
        self,
        registry: HealthRegistry,
        *,
        gateway: TelegramGateway | None = None,
    ) -> None:
        """Connect gateway (when credentials present) and start discovery task.

        When credentials are missing the web UI stays up; discovery health is
        ``blocked`` with ``telegram_credentials_missing``.
        """
        from telegram_lead_discovery.security.secrets import load_secret_presence

        if self._started:
            return

        presence = load_secret_presence()
        if not presence.telegram_ready:
            self.credentials_present = False
            self.start_disabled_reason = START_DISABLED_TELEGRAM_CREDENTIALS_MISSING
            self.gateway = None
            mark_discovery_blocked(
                reason_code=START_DISABLED_TELEGRAM_CREDENTIALS_MISSING,
                registry=registry,
            )
            logger.emit(
                level="warning",
                event_code="discovery.blocked",
                result="blocked",
                fields={"reason_code": START_DISABLED_TELEGRAM_CREDENTIALS_MISSING},
            )
            self._started = True
            return

        self.credentials_present = True
        self.start_disabled_reason = None

        if gateway is not None:
            self.gateway = gateway
        else:
            from telegram_lead_discovery.collector.adapter.telethon_gateway import (
                TelethonTelegramGateway,
            )

            self.gateway = TelethonTelegramGateway()

        try:
            await self.gateway.connect()
        except Exception as exc:  # noqa: BLE001 — UI must stay up
            self.gateway = None
            # OBS-018: discovery states are healthy|degraded|blocked|stopped.
            mark_discovery_blocked(
                reason_code="telegram_connect_failed",
                registry=registry,
            )
            logger.emit(
                level="error",
                event_code="telegram_gateway.connect_failed",
                result="failed",
                fields={"error_type": type(exc).__name__},
            )
            self._started = True
            return

        self.discovery_loop = KeywordDiscoveryClaimLoop(self.gateway)
        self.discovery_loop.start()
        mark_discovery_healthy(registry=registry)
        logger.emit(
            level="info",
            event_code="discovery.worker_started",
            result="ok",
        )
        self._started = True

    async def shutdown(self) -> None:
        """Stop claim loop (await short op / leave lease), then disconnect gateway."""
        loop = self.discovery_loop
        if loop is not None:
            logger.emit(
                level="info",
                event_code="discovery.worker_stopping",
                result="ok",
            )
            await loop.stop()
            self.discovery_loop = None

        gateway = self.gateway
        if gateway is not None:
            disconnect = getattr(gateway, "disconnect", None)
            if callable(disconnect):
                try:
                    await disconnect()
                except Exception as exc:  # noqa: BLE001
                    logger.emit(
                        level="warning",
                        event_code="telegram_gateway.disconnect_failed",
                        result="failed",
                        fields={"error_type": type(exc).__name__},
                    )
            self.gateway = None

        mark_discovery_stopped(reason_code="worker_stopped")
        logger.emit(
            level="info",
            event_code="runtime.coordinator_stopped",
            result="ok",
        )


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
    from telegram_lead_discovery.security.secrets import hydrate_environ_from_secret_files

    configure_logging()
    assert_loopback_bind(bind)
    ensure_directories()
    hydrate_environ_from_secret_files()

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
            from telegram_lead_discovery.source_discovery.profile_service import (
                ensure_seed_keyword_profile,
            )

            await seed_ruleset_ru_mvp_1(session)
            await ensure_seed_keyword_profile(session)
            recovered = await recover_stale_jobs(session)
        logger.emit(
            level="info",
            event_code="jobs.recovered",
            result="ok",
            fields={"recovered": recovered},
        )
        registry.set_component("settings", HealthState.HEALTHY)
        registry.mark_ready()

        # INF-003: web -> TelegramGateway -> workers; runtime healthy after workers.
        from telegram_lead_discovery.dashboard.app import create_app

        app = create_app()
        coordinator = RuntimeCoordinator()
        await coordinator.start(registry)
        app.state.gateway = coordinator.gateway
        app.state.runtime_coordinator = coordinator
        app.state.telegram_credentials_present = coordinator.credentials_present
        app.state.discovery_start_disabled_reason = coordinator.start_disabled_reason

        registry.set_component("web", HealthState.HEALTHY)
        registry.set_component("runtime", HealthState.HEALTHY)

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
            # Shutdown: stop claim loop, await short op / leave lease,
            # disconnect gateway, then release process lock (Uvicorn already exiting).
            await coordinator.shutdown()
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

        async def _backup(session: Any) -> Any:
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

        async def _purge(session: Any) -> Any:
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
