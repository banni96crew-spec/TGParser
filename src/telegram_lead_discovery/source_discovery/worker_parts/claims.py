from __future__ import annotations

from telegram_lead_discovery.source_discovery.worker_parts.dependencies import *

from telegram_lead_discovery.source_discovery.worker_parts.coordinator import (
    process_keyword_discovery_job,
)
from telegram_lead_discovery.source_discovery.worker_parts.graph_worker import (
    process_graph_discovery_job,
)


async def claim_and_process_keyword_job(
    session: AsyncSession,
    gateway: TelegramGateway,
    *,
    owner: str = "keyword-discovery-worker",
) -> dict[str, Any] | None:
    """Recover stale leases, claim one keyword job, process it."""
    await recover_stale_jobs(session)
    job = await claim_job(
        session,
        job_types=[JOB_TYPE_KEYWORD_DISCOVERY],
        owner=owner,
    )
    if job is None:
        return None
    return await process_keyword_discovery_job(session, job, gateway)


# Idle poll between empty claims. FloodWait jobs wake via Job.available_at — no long sleep.
CLAIM_LOOP_IDLE_SECONDS = 2.0
CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS = 30.0

_log = logging.getLogger("tld.source_discovery.worker")


class KeywordDiscoveryClaimLoop:
    """Asyncio claim loop for ``keyword_discovery`` jobs (INF-021).

    Not a FastAPI BackgroundTask — started as ``asyncio.create_task`` by runtime.
    On stop: finish the current short claim/process cycle when possible; leave any
    in-flight lease for ``recover_stale_jobs`` if the wait times out.
    """

    def __init__(
        self,
        gateway: TelegramGateway,
        *,
        idle_seconds: float = CLAIM_LOOP_IDLE_SECONDS,
        owner: str = "keyword-discovery-worker",
        shutdown_timeout_seconds: float = CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._idle_seconds = idle_seconds
        self._owner = owner
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="keyword-discovery-claim-loop",
        )
        return self._task

    async def stop(self) -> None:
        """Stop accepting new claims; await current short op up to timeout."""
        self._stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=self._shutdown_timeout_seconds)
        except TimeoutError:
            _log.warning(
                "keyword discovery claim loop shutdown timed out; "
                "leaving lease for recover_stale_jobs"
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    async def _run(self) -> None:
        from telegram_lead_discovery.storage.db import session_scope

        while not self._stop.is_set():
            claimed = False
            try:
                async with session_scope() as session:
                    outcome = await claim_and_process_keyword_job(
                        session,
                        self._gateway,
                        owner=self._owner,
                    )
                    claimed = outcome is not None
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — loop must not die on one job failure
                _log.exception("keyword discovery claim/process failed")
                claimed = True  # brief backoff via idle wait below

            if self._stop.is_set():
                break
            if claimed:
                # Yield to event loop before claiming next job.
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._idle_seconds)
                break
            except TimeoutError:
                continue


class GraphDiscoveryClaimLoop:
    """Asyncio claim loop for ``graph_discovery`` jobs (INF-022 / D-066)."""

    def __init__(
        self,
        gateway: TelegramGateway,
        *,
        idle_seconds: float = CLAIM_LOOP_IDLE_SECONDS,
        owner: str = "graph-discovery-worker",
        shutdown_timeout_seconds: float = CLAIM_LOOP_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._idle_seconds = idle_seconds
        self._owner = owner
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="graph-discovery-claim-loop",
        )
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=self._shutdown_timeout_seconds)
        except TimeoutError:
            _log.warning(
                "graph discovery claim loop shutdown timed out; "
                "leaving lease for recover_stale_jobs"
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    async def _run(self) -> None:
        from telegram_lead_discovery.storage.db import session_scope

        while not self._stop.is_set():
            claimed = False
            try:
                async with session_scope() as session:
                    outcome = await claim_and_process_graph_job(
                        session,
                        self._gateway,
                        owner=self._owner,
                    )
                    claimed = outcome is not None
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — one job must not kill the loop
                _log.exception("graph discovery claim/process failed")
                claimed = True

            if self._stop.is_set():
                break
            if claimed:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._idle_seconds)
                break
            except TimeoutError:
                continue


async def claim_and_process_graph_job(
    session: AsyncSession,
    gateway: TelegramGateway,
    *,
    owner: str = "graph-discovery-worker",
    cancel_requested: bool = False,
) -> dict[str, Any] | None:
    """Recover stale leases, claim one graph discovery job, process it."""
    from telegram_lead_discovery.source_discovery.graph_discovery import (
        JOB_TYPE_GRAPH_DISCOVERY,
    )

    await recover_stale_jobs(session)
    job = await claim_job(
        session,
        job_types=[JOB_TYPE_GRAPH_DISCOVERY],
        owner=owner,
    )
    if job is None:
        return None
    return await process_graph_discovery_job(
        session, job, gateway, cancel_requested=cancel_requested
    )
