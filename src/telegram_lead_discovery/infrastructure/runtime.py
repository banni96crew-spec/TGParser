"""Application runtime — startup order INF-003, named loops INF-022 / D-066."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from telegram_lead_discovery.collector.ports import TelegramGateway
from telegram_lead_discovery.collector.service import (
    claim_and_process_collector_job,
    consume_live_updates,
    enqueue_periodic_reconciliation,
    enqueue_startup_reconciliation,
)
from telegram_lead_discovery.infrastructure.paths import (
    database_path,
    ensure_directories,
    lock_path,
)
from telegram_lead_discovery.infrastructure.process_lock import ProcessLock
from telegram_lead_discovery.notifications.worker import NotificationOutboxLoop
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
from telegram_lead_discovery.processing.pipeline import (
    ProcessingClaimLoop,
    recover_stale_envelopes,
)
from telegram_lead_discovery.security.bind_guard import assert_loopback_bind
from telegram_lead_discovery.security.preflight import run_security_preflight
from telegram_lead_discovery.settings.service import seed_defaults
from telegram_lead_discovery.source_discovery.worker import (
    GraphDiscoveryClaimLoop,
    KeywordDiscoveryClaimLoop,
)
from telegram_lead_discovery.storage.db import (
    init_engine,
    integrity_check_ok,
    pragma_probe,
    session_scope,
)
from telegram_lead_discovery.storage.jobs import recover_stale_jobs
from telegram_lead_discovery.storage.migrate import upgrade_head
from telegram_lead_discovery.storage.outbox import recover_stale_outbox
from telegram_lead_discovery.storage.session import run_write

logger = StructuredLogger("INF")

START_DISABLED_TELEGRAM_CREDENTIALS_MISSING = "telegram_credentials_missing"
PERIODIC_RECONCILE_SECONDS = 15 * 60
WATCHDOG_INTERVAL_SECONDS = 60.0
LOOP_IDLE_SECONDS = 0.5
LOOP_SHUTDOWN_TIMEOUT_SECONDS = 30.0


def _task_alive(task: asyncio.Task[Any] | None) -> bool:
    return task is not None and not task.done()


@dataclass
class SupervisedLoop:
    """Named asyncio loop: isolated failures, restartable, graceful stop."""

    name: str
    factory: Callable[[], Any]
    _stop: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _task: asyncio.Task[None] | None = field(default=None, repr=False)
    _last_error: str | None = field(default=None, repr=False)
    _restart_count: int = field(default=0, repr=False)
    idle_seconds: float = LOOP_IDLE_SECONDS
    shutdown_timeout_seconds: float = LOOP_SHUTDOWN_TIMEOUT_SECONDS

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def running(self) -> bool:
        return _task_alive(self._task)

    def start(self) -> asyncio.Task[None]:
        if self.running:
            return self._task  # type: ignore[return-value]
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=self.name)
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=self.shutdown_timeout_seconds)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    def ensure_running(self) -> bool:
        """Restart if the task died unexpectedly. Returns True if a restart happened."""
        if self._stop.is_set():
            return False
        if self.running:
            return False
        self._restart_count += 1
        self._task = asyncio.create_task(self._run(), name=self.name)
        return True

    async def _run(self) -> None:
        body = self.factory()
        try:
            await body(self._stop)
            self._last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one loop must not kill the process
            self._last_error = type(exc).__name__
            logging.getLogger("tld.runtime").exception("supervised loop %s failed", self.name)


@dataclass
class RuntimeCoordinator:
    """Owns shared TelegramGateway + named runtime loops (INF-021 / INF-022 / D-066)."""

    gateway: TelegramGateway | None = None
    credentials_present: bool = False
    start_disabled_reason: str | None = None
    discovery_loop: KeywordDiscoveryClaimLoop | None = field(default=None, repr=False)
    graph_loop: GraphDiscoveryClaimLoop | None = field(default=None, repr=False)
    processing_loop: ProcessingClaimLoop | None = field(default=None, repr=False)
    notification_loop: NotificationOutboxLoop | None = field(default=None, repr=False)
    collector_job_loop: SupervisedLoop | None = field(default=None, repr=False)
    live_updates_loop: SupervisedLoop | None = field(default=None, repr=False)
    reconciliation_loop: SupervisedLoop | None = field(default=None, repr=False)
    watchdog_loop: SupervisedLoop | None = field(default=None, repr=False)
    startup_token: str = field(default_factory=lambda: uuid.uuid4().hex)
    notification_client_factory: Callable[[], Any] | None = field(default=None, repr=False)
    periodic_reconcile_seconds: float = PERIODIC_RECONCILE_SECONDS
    idle_seconds: float = LOOP_IDLE_SECONDS
    _registry: HealthRegistry | None = field(default=None, repr=False)
    _started: bool = field(default=False, repr=False)
    _heartbeat_at: dict[str, datetime] = field(default_factory=dict, repr=False)

    @property
    def worker_running(self) -> bool:
        loop = self.discovery_loop
        return loop is not None and loop.task is not None and not loop.task.done()

    def named_loops_running(self) -> dict[str, bool]:
        return {
            "keyword_discovery": self.worker_running,
            "graph_discovery": _task_alive(
                self.graph_loop.task if self.graph_loop is not None else None
            ),
            "collector_jobs": bool(
                self.collector_job_loop is not None and self.collector_job_loop.running
            ),
            "live_updates": bool(
                self.live_updates_loop is not None and self.live_updates_loop.running
            ),
            "processing": _task_alive(
                self.processing_loop.task if self.processing_loop is not None else None
            ),
            "notifications": _task_alive(
                self.notification_loop.task if self.notification_loop is not None else None
            ),
            "reconciliation": bool(
                self.reconciliation_loop is not None and self.reconciliation_loop.running
            ),
            "watchdog": bool(self.watchdog_loop is not None and self.watchdog_loop.running),
        }

    def _beat(self, name: str) -> None:
        self._heartbeat_at[name] = datetime.now(UTC)

    def _set_health(
        self,
        component: str,
        state: HealthState,
        *,
        reason_code: str | None = None,
    ) -> None:
        registry = self._registry
        if registry is None:
            return
        registry.set_component(component, state, reason_code=reason_code)

    async def start(
        self,
        registry: HealthRegistry,
        *,
        gateway: TelegramGateway | None = None,
    ) -> None:
        """Connect gateway (when credentials present) and start named loops."""
        from telegram_lead_discovery.security.secrets import load_secret_presence

        if self._started:
            return

        self._registry = registry
        presence = load_secret_presence()
        if not presence.telegram_ready:
            self.credentials_present = False
            self.start_disabled_reason = START_DISABLED_TELEGRAM_CREDENTIALS_MISSING
            self.gateway = None
            mark_discovery_blocked(
                reason_code=START_DISABLED_TELEGRAM_CREDENTIALS_MISSING,
                registry=registry,
            )
            self._set_health(
                "collector",
                HealthState.BLOCKED,
                reason_code=START_DISABLED_TELEGRAM_CREDENTIALS_MISSING,
            )
            # Processing / notifications / watchdog still run without Telegram.
            await self._start_non_telegram_loops()
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
            mark_discovery_blocked(
                reason_code="telegram_connect_failed",
                registry=registry,
            )
            self._set_health(
                "collector",
                HealthState.BLOCKED,
                reason_code="telegram_connect_failed",
            )
            logger.emit(
                level="error",
                event_code="telegram_gateway.connect_failed",
                result="failed",
                fields={"error_type": type(exc).__name__},
            )
            await self._start_non_telegram_loops()
            self._started = True
            return

        self.discovery_loop = KeywordDiscoveryClaimLoop(
            self.gateway, idle_seconds=self.idle_seconds
        )
        self.discovery_loop.start()
        self.graph_loop = GraphDiscoveryClaimLoop(
            self.gateway, idle_seconds=self.idle_seconds
        )
        self.graph_loop.start()
        mark_discovery_healthy(registry=registry)

        self.collector_job_loop = SupervisedLoop(
            name="collector-job-loop",
            factory=self._collector_job_body,
            idle_seconds=self.idle_seconds,
        )
        self.collector_job_loop.start()

        self.live_updates_loop = SupervisedLoop(
            name="live-updates-loop",
            factory=self._live_updates_body,
            idle_seconds=self.idle_seconds,
            shutdown_timeout_seconds=5.0,
        )
        self.live_updates_loop.start()

        await self._start_non_telegram_loops()

        # Startup reconciliation for monitoring sources (D-019).
        async with session_scope() as session:
            enqueued = await enqueue_startup_reconciliation(
                session, startup_token=self.startup_token
            )
        logger.emit(
            level="info",
            event_code="reconciliation.startup_enqueued",
            result="ok",
            fields={"jobs": enqueued},
        )

        self.reconciliation_loop = SupervisedLoop(
            name="reconciliation-scheduler-loop",
            factory=self._reconciliation_body,
            idle_seconds=self.idle_seconds,
        )
        self.reconciliation_loop.start()

        self._set_health("collector", HealthState.HEALTHY, reason_code="loops_running")
        self._set_health("reconciliation", HealthState.HEALTHY, reason_code="scheduled")
        self._beat("collector")
        self._beat("discovery")
        self._beat("reconciliation")

        logger.emit(
            level="info",
            event_code="discovery.worker_started",
            result="ok",
        )
        logger.emit(
            level="info",
            event_code="runtime.named_loops_started",
            result="ok",
            fields=self.named_loops_running(),
        )
        self._publish_named_loop_health()
        self._started = True

    def _publish_named_loop_health(self) -> None:
        """Project INF-022 running map onto OBS-020 loop component names."""
        from telegram_lead_discovery.observability.loops import apply_named_loop_running_map

        monitoring_count = 0
        # Count is optional; UI/tests do not require DB here.
        apply_named_loop_running_map(
            self.named_loops_running(),
            registry=self._registry,
            credentials_present=bool(self.credentials_present),
            monitoring_source_count=monitoring_count,
        )

    async def _start_non_telegram_loops(self) -> None:
        self.processing_loop = ProcessingClaimLoop(idle_seconds=self.idle_seconds)
        self.processing_loop.start()
        self._set_health("processing", HealthState.HEALTHY, reason_code="loops_running")
        self._beat("processing")

        self.notification_loop = NotificationOutboxLoop(
            idle_seconds=self.idle_seconds,
            client_factory=self.notification_client_factory,
        )
        self.notification_loop.start()
        reason = "delivery_shadow_or_ready"
        self._set_health("notifications", HealthState.HEALTHY, reason_code=reason)
        self._beat("notifications")

        self.watchdog_loop = SupervisedLoop(
            name="health-watchdog-loop",
            factory=self._watchdog_body,
            idle_seconds=WATCHDOG_INTERVAL_SECONDS,
        )
        self.watchdog_loop.start()
        self._set_health("runtime", HealthState.HEALTHY, reason_code="watchdog_running")
        self._beat("watchdog")

    def _collector_job_body(self) -> Callable[[asyncio.Event], Any]:
        async def _body(stop: asyncio.Event) -> None:
            gateway = self.gateway
            if gateway is None:
                return
            while not stop.is_set():
                claimed = False
                try:
                    outcome = await claim_and_process_collector_job(
                        gateway, owner="collector-job-worker"
                    )
                    claimed = outcome is not None
                    self._beat("collector")
                    self._set_health(
                        "collector", HealthState.HEALTHY, reason_code="loops_running"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._set_health(
                        "collector",
                        HealthState.DEGRADED,
                        reason_code=type(exc).__name__,
                    )
                    logging.getLogger("tld.runtime").exception("collector job loop failed")
                    claimed = True
                if stop.is_set():
                    break
                if claimed:
                    await asyncio.sleep(0)
                    continue
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.idle_seconds)
                    break
                except TimeoutError:
                    continue

        return _body

    def _live_updates_body(self) -> Callable[[asyncio.Event], Any]:
        async def _body(stop: asyncio.Event) -> None:
            gateway = self.gateway
            if gateway is None:
                return
            while not stop.is_set():
                try:
                    result = await consume_live_updates(
                        gateway,
                        write=run_write,
                        should_stop=stop.is_set,
                    )
                    self._beat("live_updates")
                    reason = result.get("health_reason")
                    if reason:
                        self._set_health(
                            "collector",
                            HealthState.DEGRADED,
                            reason_code=str(reason),
                        )
                    else:
                        self._set_health(
                            "collector",
                            HealthState.HEALTHY,
                            reason_code="live_running",
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._set_health(
                        "collector",
                        HealthState.DEGRADED,
                        reason_code=type(exc).__name__,
                    )
                    logging.getLogger("tld.runtime").exception("live updates loop failed")
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self.idle_seconds)
                        break
                    except TimeoutError:
                        continue
                if stop.is_set():
                    break
                # iter_updates ended (e.g. fake close) — brief idle then retry unless stopping
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.idle_seconds)
                    break
                except TimeoutError:
                    continue

        return _body

    def _reconciliation_body(self) -> Callable[[asyncio.Event], Any]:
        async def _body(stop: asyncio.Event) -> None:
            # First periodic tick after interval (startup already enqueued).
            while not stop.is_set():
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=self.periodic_reconcile_seconds
                    )
                    break
                except TimeoutError:
                    pass
                if stop.is_set():
                    break
                try:

                    async def _enqueue(session: Any) -> int:
                        return await enqueue_periodic_reconciliation(session)

                    count = await run_write(_enqueue)
                    self._beat("reconciliation")
                    self._set_health(
                        "reconciliation",
                        HealthState.HEALTHY,
                        reason_code="periodic_enqueued",
                    )
                    logger.emit(
                        level="info",
                        event_code="reconciliation.periodic_enqueued",
                        result="ok",
                        fields={"jobs": count},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._set_health(
                        "reconciliation",
                        HealthState.DEGRADED,
                        reason_code=type(exc).__name__,
                    )
                    logging.getLogger("tld.runtime").exception(
                        "periodic reconciliation enqueue failed"
                    )

        return _body

    def _watchdog_body(self) -> Callable[[asyncio.Event], Any]:
        async def _body(stop: asyncio.Event) -> None:
            while not stop.is_set():
                try:
                    await self._watchdog_tick()
                    self._beat("watchdog")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._set_health(
                        "runtime",
                        HealthState.DEGRADED,
                        reason_code=type(exc).__name__,
                    )
                    logging.getLogger("tld.runtime").exception("watchdog tick failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=WATCHDOG_INTERVAL_SECONDS)
                    break
                except TimeoutError:
                    continue

        return _body

    async def _watchdog_tick(self) -> None:
        async def _recover(session: Any) -> dict[str, int]:
            jobs = await recover_stale_jobs(session)
            envs = await recover_stale_envelopes(session)
            outbox = await recover_stale_outbox(session)
            return {"jobs": jobs, "envelopes": envs, "outbox": outbox}

        recovered = await run_write(_recover)
        if any(recovered.values()):
            logger.emit(
                level="info",
                event_code="runtime.lease_recovered",
                result="ok",
                fields=recovered,
            )

        # Restart dead loops without killing siblings.
        restarted: list[str] = []
        if self.discovery_loop is not None:
            task = self.discovery_loop.task
            if task is not None and task.done() and self.gateway is not None:
                self.discovery_loop.start()
                restarted.append("keyword_discovery")
        if self.graph_loop is not None:
            task = self.graph_loop.task
            if task is not None and task.done() and self.gateway is not None:
                self.graph_loop.start()
                restarted.append("graph_discovery")
        if self.processing_loop is not None:
            task = self.processing_loop.task
            if task is not None and task.done():
                self.processing_loop.start()
                restarted.append("processing")
                self._set_health(
                    "processing", HealthState.DEGRADED, reason_code="loop_restarted"
                )
        if self.notification_loop is not None:
            task = self.notification_loop.task
            if task is not None and task.done():
                self.notification_loop.start()
                restarted.append("notifications")
                self._set_health(
                    "notifications", HealthState.DEGRADED, reason_code="loop_restarted"
                )
        for attr in ("collector_job_loop", "live_updates_loop", "reconciliation_loop"):
            loop = getattr(self, attr)
            if loop is not None and loop.ensure_running():
                restarted.append(loop.name)
                if attr.startswith("collector") or attr.startswith("live"):
                    self._set_health(
                        "collector", HealthState.DEGRADED, reason_code="loop_restarted"
                    )

        if self.processing_loop is not None and self.processing_loop.last_error:
            self._set_health(
                "processing",
                HealthState.DEGRADED,
                reason_code=self.processing_loop.last_error,
            )
        elif self.processing_loop is not None and _task_alive(self.processing_loop.task):
            self._set_health(
                "processing", HealthState.HEALTHY, reason_code="loops_running"
            )

        if self.notification_loop is not None:
            if self.notification_loop.last_error:
                self._set_health(
                    "notifications",
                    HealthState.DEGRADED,
                    reason_code=self.notification_loop.last_error,
                )
            elif self.notification_loop.delivery_disabled:
                self._set_health(
                    "notifications",
                    HealthState.HEALTHY,
                    reason_code="delivery_disabled",
                )
            elif _task_alive(self.notification_loop.task):
                self._set_health(
                    "notifications", HealthState.HEALTHY, reason_code="loops_running"
                )

        # Credentials + monitoring: collector must not stay deferred/STOPPED.
        if self.credentials_present and self.gateway is not None:
            collector = (
                self._registry.components.get("collector") if self._registry else None
            )
            if collector is not None and collector.state is HealthState.STOPPED:
                self._set_health(
                    "collector", HealthState.HEALTHY, reason_code="loops_running"
                )

        if restarted:
            logger.emit(
                level="warning",
                event_code="runtime.loops_restarted",
                result="degraded",
                fields={"loops": restarted},
            )

    async def shutdown(self) -> None:
        """Stop named loops, then disconnect gateway."""
        gateway = self.gateway

        # Signal stop on supervised loops first (non-blocking flag).
        for loop in (
            self.watchdog_loop,
            self.reconciliation_loop,
            self.collector_job_loop,
            self.live_updates_loop,
        ):
            if loop is not None:
                loop._stop.set()  # noqa: SLF001 — coordinated shutdown

        for loop in (
            self.discovery_loop,
            self.graph_loop,
            self.processing_loop,
            self.notification_loop,
        ):
            if loop is not None and hasattr(loop, "_stop"):
                loop._stop.set()  # noqa: SLF001

        # Unblock iter_updates waiters before awaiting live loop stop.
        if gateway is not None:
            close_updates = getattr(gateway, "close_updates", None)
            if callable(close_updates):
                try:
                    await close_updates()
                except Exception:  # noqa: BLE001
                    pass

        for loop in (
            self.watchdog_loop,
            self.reconciliation_loop,
            self.discovery_loop,
            self.graph_loop,
            self.collector_job_loop,
            self.live_updates_loop,
            self.processing_loop,
            self.notification_loop,
        ):
            if loop is None:
                continue
            stop = getattr(loop, "stop", None)
            if callable(stop):
                try:
                    await stop()
                except Exception as exc:  # noqa: BLE001
                    logger.emit(
                        level="warning",
                        event_code="runtime.loop_stop_failed",
                        result="failed",
                        fields={"error_type": type(exc).__name__},
                    )

        self.discovery_loop = None
        self.graph_loop = None
        self.collector_job_loop = None
        self.live_updates_loop = None
        self.processing_loop = None
        self.notification_loop = None
        self.reconciliation_loop = None
        self.watchdog_loop = None

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
        self._set_health("collector", HealthState.STOPPED, reason_code="worker_stopped")
        self._set_health("processing", HealthState.STOPPED, reason_code="worker_stopped")
        self._set_health(
            "notifications", HealthState.STOPPED, reason_code="worker_stopped"
        )
        self._set_health(
            "reconciliation", HealthState.STOPPED, reason_code="worker_stopped"
        )
        logger.emit(
            level="info",
            event_code="runtime.coordinator_stopped",
            result="ok",
        )
        self._started = False


async def run_migrations() -> None:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    upgrade_head(path)
    await init_engine(path)


async def seed_startup_catalog(session: Any) -> None:
    """Startup catalog seed boundary used by ``run_command`` start/run.

    MUST activate the current remediation catalog (``seed_active_ruleset`` →
    ``ru-mvp-3``), never historical ``seed_ruleset_ru_mvp_1`` alone. Checksum
    mismatch fails loudly via ``seed_active_ruleset`` (no silent fallback).
    """
    from telegram_lead_discovery.detection.seed import seed_active_ruleset
    from telegram_lead_discovery.source_discovery.profile_service import (
        ensure_seed_keyword_profile,
    )

    await seed_active_ruleset(session)
    await ensure_seed_keyword_profile(session)


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

    if command in {"start", "run"}:
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
            # Will be set to HEALTHY by coordinator when credentials + loops start.
            # Must NOT remain permanent STOPPED/deferred (D-066 / INF-022).
            registry.set_component(
                "collector", HealthState.STARTING, reason_code="starting_loops"
            )

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
            await seed_startup_catalog(session)
            recovered = await recover_stale_jobs(session)
            await recover_stale_envelopes(session)
            await recover_stale_outbox(session)
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
        if registry.components.get("runtime", None) is None or registry.components[
            "runtime"
        ].state in {HealthState.STARTING, HealthState.STOPPED}:
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
            await coordinator.shutdown()
            lock.release()
        return 0

    if command == "backup":
        from telegram_lead_discovery.infrastructure.backup import (
            create_online_backup,
            rotate_backups,
        )
        from telegram_lead_discovery.infrastructure.paths import resolve_app_paths

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
