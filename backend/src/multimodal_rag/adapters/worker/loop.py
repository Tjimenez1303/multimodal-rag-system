"""Claim loop of the ingestion worker.

The worker claims one job at a time and runs it to completion while a heartbeat renews
its lease. When no job is pending it sleeps until a job is enqueued or the poll
interval elapses. An attempt ends early when:

- a stop is requested, and no further job is claimed;
- the lease is lost to another worker, which reclaimed the job after the lease expired;
- the database becomes unavailable.

The abandoned job keeps its ``processing`` state until its lease expires, and then
another claim retries it from scratch. After a budget of jobs the loop returns, so the
process exits, releases the memory extraction accumulates, and compose restarts it.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from multimodal_rag.ingestion.domain import IngestionJob
from multimodal_rag.ingestion.errors import LeaseLostError
from multimodal_rag.ingestion.ports import JobQueue
from multimodal_rag.shared.errors import StorageTimeoutError, StorageUnavailableError
from multimodal_rag.shared.logging import bind_correlation, clear_correlation
from multimodal_rag.shared.resilience import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

# Database failures that may pass, so they never fail a job
_DATABASE_OUTAGES = (StorageUnavailableError, StorageTimeoutError)


class JobWakeups(Protocol):
    """Source of the signal that a job may be waiting."""

    async def wait(self) -> None:
        """Return when a job is enqueued. Callers bound the wait with a timeout."""
        ...


class WorkerLoop:
    """Claims ingestion jobs and runs them one at a time.

    Args:
        jobs: Job queue.
        process: Runs one claimed attempt, such as ``ProcessJob``.
        wakeups: Signal that a job was enqueued.
        worker_id: Holder name written on each claimed job.
        lease_seconds: Lease granted per claim and per renewal.
        heartbeat_seconds: Interval between two lease renewals.
        poll_seconds: Longest sleep between two claims.
        claim_retry: Backoff of claims while the database is unavailable.
        max_jobs: Attempts run before the loop returns so the process restarts.
    """

    def __init__(
        self,
        *,
        jobs: JobQueue,
        process: Callable[[IngestionJob], Awaitable[IngestionJob]],
        wakeups: JobWakeups,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: float,
        poll_seconds: float,
        claim_retry: RetryPolicy,
        max_jobs: int,
    ) -> None:
        self._jobs = jobs
        self._process = process
        self._wakeups = wakeups
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._poll_seconds = poll_seconds
        self._claim_retry = claim_retry
        self._max_jobs = max_jobs

    async def run(self, *, stop: asyncio.Event) -> None:
        """Claim and process jobs until ``stop`` is set or the job budget is spent.

        Args:
            stop: Event that ends the loop and cancels a running attempt.
        """
        attempts = 0

        # Keep working until asked to stop or until the job budget is spent
        while not stop.is_set() and attempts < self._max_jobs:
            try:
                # Claim the oldest claimable job, giving up only if stop is requested
                job = await _first_of(self._claim(), stop)
            except Exception:
                logger.exception("claiming a job failed for good, the worker stops")
                raise
            if stop.is_set():
                break

            # Nothing to do: sleep until a job is enqueued or the poll interval passes
            if job is None:
                await _first_of(self._sleep_until_woken(), stop)
                continue

            # Run the attempt while a heartbeat keeps its lease alive
            await self._attempt(job, stop)
            attempts += 1

        # Exit so compose restarts the process with fresh memory
        if attempts >= self._max_jobs:
            logger.info("worker ran %s jobs, exiting to be restarted", attempts)

    async def _claim(self) -> IngestionJob | None:
        # A database outage is retried until the database answers again. Any other
        # error is not transient, so it ends the worker and compose restarts it.
        return await call_with_retry(
            self._claim_retry,
            lambda: self._jobs.claim(
                worker_id=self._worker_id, lease_seconds=self._lease_seconds
            ),
            on=_DATABASE_OUTAGES,
        )

    async def _sleep_until_woken(self) -> None:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(self._poll_seconds):
                await self._wakeups.wait()

    async def _attempt(self, job: IngestionJob, stop: asyncio.Event) -> None:
        # Tag every log line of this attempt with its request and job ids
        clear_correlation()
        bind_correlation(request_id=job.correlation_id, job_id=str(job.id))
        logger.info("job claimed")

        # Renew the lease in the background while the job runs
        heartbeat = asyncio.ensure_future(self._keep_leased(job.id, job.held_lease()))
        try:
            # Run the job until it finishes, stop is requested or the lease is lost
            finished = await _first_of(self._process(job), stop, heartbeat)
            if finished is None:
                logger.warning("stop requested, attempt %s abandoned", job.attempt)
        except LeaseLostError:
            logger.warning("lease lost to another worker, attempt abandoned")
        except _DATABASE_OUTAGES as error:
            logger.warning("database unavailable (%s), attempt abandoned", error.code)
        except Exception:  # one broken job must not end the worker
            logger.exception("job attempt ended unexpectedly")
        finally:
            # Always stop the heartbeat and clear the log context
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            clear_correlation()

    async def _keep_leased(self, job_id: uuid.UUID, lease_token: uuid.UUID) -> None:
        # Renews until cancelled. A lost lease ends the attempt, an outage does not,
        # because the lease outlives a few missed renewals.
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                await self._jobs.heartbeat(
                    job_id=job_id,
                    lease_token=lease_token,
                    lease_seconds=self._lease_seconds,
                )
            except _DATABASE_OUTAGES as error:
                logger.warning("renewing the lease failed (%s)", error.code)


async def _first_of[T](
    work: Awaitable[T],
    stop: asyncio.Event,
    guard: asyncio.Future[None] | None = None,
) -> T | None:
    """Await ``work`` until ``stop`` or ``guard`` ends first, then cancel it.

    Returns:
        The result of ``work``, or ``None`` when ``stop`` came first.

    Raises:
        Exception: The error of ``work``, or of ``guard`` when it failed first.
    """
    # Race the work against the stop signal and the optional guard
    task = asyncio.ensure_future(work)
    stopped = asyncio.ensure_future(stop.wait())
    waited = {task, stopped} if guard is None else {task, stopped, guard}
    try:
        await asyncio.wait(waited, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Also runs when the caller itself is cancelled, so the work never outlives it.
        stopped.cancel()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    # The work was cancelled: surface the guard's error, if it failed
    if task.cancelled():
        if guard is not None and guard.done() and not guard.cancelled():
            guard.result()  # raises the guard's error, such as a lost lease
        return None
    return task.result()
