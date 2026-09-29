import asyncio
import io
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator

import pytest
import stamina

from multimodal_rag.adapters.worker.loop import WorkerLoop
from multimodal_rag.ingestion.domain import IngestionJob, JobStatus, JobSummary
from multimodal_rag.ingestion.errors import LeaseLostError
from multimodal_rag.shared.errors import StorageUnavailableError
from multimodal_rag.shared.logging import configure_logging
from multimodal_rag.shared.resilience import RetryPolicy
from tests.fakes import FrozenClock, InMemoryJobQueue, pending_job

Process = Callable[[IngestionJob], Awaitable[IngestionJob]]


class ManualWakeups:
    """Wake-up source that a test triggers by hand."""

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.waits = 0

    async def wait(self) -> None:
        self.waits += 1
        await self.event.wait()
        self.event.clear()


class FlakyQueue(InMemoryJobQueue):
    """Fails its first claims, as a database restart would."""

    def __init__(self, clock: FrozenClock, *, failures: int = 1) -> None:
        super().__init__(clock)
        self.failures = failures

    async def claim(self, *, worker_id: str, lease_seconds: int) -> IngestionJob | None:
        if self.failures:
            self.failures -= 1
            raise StorageUnavailableError("database restarting")
        return await super().claim(worker_id=worker_id, lease_seconds=lease_seconds)


@pytest.fixture(autouse=True)
def instant_retries() -> Iterator[None]:
    # stamina's testing mode skips the waits and bounds the attempts.
    with stamina.set_testing(True, attempts=10):
        yield


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging(log_format="json", stream=stream)
    yield stream
    logging.getLogger().handlers = []


def records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


async def enqueue(
    jobs: InMemoryJobQueue, correlation_id: str = "req-1"
) -> IngestionJob:
    job, _ = await jobs.enqueue(pending_job(jobs.clock, correlation_id=correlation_id))
    return job


def loop_for(
    jobs: InMemoryJobQueue,
    process: Process,
    wakeups: ManualWakeups,
    *,
    heartbeat_seconds: float = 30,
    max_jobs: int = 100,
) -> WorkerLoop:
    return WorkerLoop(
        jobs=jobs,
        process=process,
        wakeups=wakeups,
        worker_id="host:1",
        lease_seconds=90,
        heartbeat_seconds=heartbeat_seconds,
        poll_seconds=0.01,
        claim_retry=RetryPolicy(
            attempts=None,
            initial_wait_seconds=0.001,
            max_wait_seconds=0.004,
            jitter_seconds=0,
            timeout_seconds=None,
        ),
        max_jobs=max_jobs,
    )


class CountingHeartbeats(InMemoryJobQueue):
    """Counts lease renewals, and can lose the lease or fail transiently."""

    def __init__(self, clock: FrozenClock, *, outcome: Exception | None = None) -> None:
        super().__init__(clock)
        self.renewals = 0
        self.outcome = outcome

    async def heartbeat(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int
    ) -> None:
        self.renewals += 1
        if self.outcome is not None:
            raise self.outcome
        await super().heartbeat(
            job_id=job_id, lease_token=lease_token, lease_seconds=lease_seconds
        )


def sleeping(jobs: InMemoryJobQueue, stop: asyncio.Event, seconds: float) -> Process:
    finish = completing(jobs, stop)

    async def process(job: IngestionJob) -> IngestionJob:
        await asyncio.sleep(seconds)
        return await finish(job)

    return process


def completing(jobs: InMemoryJobQueue, stop: asyncio.Event, after: int = 1) -> Process:
    done: list[uuid.UUID] = []

    async def process(job: IngestionJob) -> IngestionJob:
        assert job.lease_token is not None
        finished = await jobs.complete(
            job_id=job.id, lease_token=job.lease_token, summary=JobSummary(pages=1)
        )
        done.append(job.id)
        if len(done) >= after:
            stop.set()
        return finished

    return process


async def test_claims_pending_jobs_and_logs_with_their_ids(
    log_stream: io.StringIO,
) -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    job = await enqueue(jobs, correlation_id="upload-7")
    stop = asyncio.Event()

    await loop_for(jobs, completing(jobs, stop), ManualWakeups()).run(stop=stop)

    stored = await jobs.get(job.id)
    assert stored.status is JobStatus.COMPLETED
    assert stored.worker_id == "host:1"
    claimed = [r for r in records(log_stream) if r["message"] == "job claimed"]
    assert claimed[0]["job_id"] == str(job.id)
    assert claimed[0]["request_id"] == "upload-7"


async def test_idle_worker_claims_a_job_once_woken() -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    wakeups = ManualWakeups()
    stop = asyncio.Event()
    worker = asyncio.create_task(
        loop_for(jobs, completing(jobs, stop), wakeups).run(stop=stop)
    )
    await asyncio.sleep(0.05)
    assert wakeups.waits > 0

    job = await enqueue(jobs)
    wakeups.event.set()
    await asyncio.wait_for(worker, timeout=2)

    assert (await jobs.get(job.id)).status is JobStatus.COMPLETED


async def test_stop_request_cancels_the_running_attempt() -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    job = await enqueue(jobs)
    stop = asyncio.Event()
    started = asyncio.Event()

    async def hang(claimed: IngestionJob) -> IngestionJob:
        started.set()
        await asyncio.sleep(3600)
        return claimed

    worker = asyncio.create_task(loop_for(jobs, hang, ManualWakeups()).run(stop=stop))
    await started.wait()
    stop.set()
    await asyncio.wait_for(worker, timeout=2)

    stored = await jobs.get(job.id)
    assert stored.status is JobStatus.PROCESSING
    assert stored.lease_token is not None


async def test_a_lost_lease_is_logged_and_the_worker_goes_on(
    log_stream: io.StringIO,
) -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    lost = await enqueue(jobs)
    kept = await enqueue(jobs)
    stop = asyncio.Event()
    finish = completing(jobs, stop)

    async def process(job: IngestionJob) -> IngestionJob:
        if job.id == lost.id:
            raise LeaseLostError("taken over")
        return await finish(job)

    await loop_for(jobs, process, ManualWakeups()).run(stop=stop)

    assert (await jobs.get(kept.id)).status is JobStatus.COMPLETED
    warnings = [r for r in records(log_stream) if r["level"] == "warning"]
    assert warnings[0]["job_id"] == str(lost.id)


async def test_unexpected_errors_are_logged_and_the_worker_goes_on(
    log_stream: io.StringIO,
) -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    job = await enqueue(jobs)
    stop = asyncio.Event()
    finish = completing(jobs, stop, after=1)
    crashed = False

    async def process(claimed: IngestionJob) -> IngestionJob:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("bug")
        return await finish(claimed)

    await enqueue(jobs)
    await loop_for(jobs, process, ManualWakeups()).run(stop=stop)

    [error] = [r for r in records(log_stream) if r["level"] == "error"]
    assert error["job_id"] == str(job.id)
    assert "bug" in str(error["exception"])


async def test_a_database_outage_during_a_job_is_a_warning(
    log_stream: io.StringIO,
) -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    job = await enqueue(jobs)
    stop = asyncio.Event()

    async def process(claimed: IngestionJob) -> IngestionJob:
        stop.set()
        raise StorageUnavailableError("database restarting")

    await loop_for(jobs, process, ManualWakeups()).run(stop=stop)

    [warning] = [r for r in records(log_stream) if r["level"] == "warning"]
    assert warning["job_id"] == str(job.id)
    assert not [r for r in records(log_stream) if r["level"] == "error"]


async def test_a_stopped_worker_claims_nothing() -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    job = await enqueue(jobs)
    stop = asyncio.Event()
    stop.set()

    await loop_for(jobs, completing(jobs, stop), ManualWakeups()).run(stop=stop)

    assert (await jobs.get(job.id)).status is JobStatus.PENDING


async def test_transient_claim_failures_are_retried_until_the_database_answers(
    log_stream: io.StringIO,
) -> None:
    jobs = FlakyQueue(FrozenClock(), failures=3)
    job = await enqueue(jobs)
    stop = asyncio.Event()

    await loop_for(jobs, completing(jobs, stop), ManualWakeups()).run(stop=stop)

    assert (await jobs.get(job.id)).status is JobStatus.COMPLETED
    retries = [
        r for r in records(log_stream) if r["message"] == "stamina.retry_scheduled"
    ]
    assert len(retries) == 3


async def test_a_claim_failing_for_another_reason_ends_the_worker(
    log_stream: io.StringIO,
) -> None:
    class BrokenQueue(InMemoryJobQueue):
        async def claim(
            self, *, worker_id: str, lease_seconds: int
        ) -> IngestionJob | None:
            raise RuntimeError("row cannot be read")

    jobs = BrokenQueue(FrozenClock())
    worker = loop_for(jobs, completing(jobs, asyncio.Event()), ManualWakeups())

    with pytest.raises(RuntimeError, match="row cannot be read"):
        await worker.run(stop=asyncio.Event())

    [error] = [r for r in records(log_stream) if r["level"] == "error"]
    assert "row cannot be read" in str(error["exception"])


async def test_cancelling_the_worker_cancels_the_running_attempt() -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    await enqueue(jobs)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def hang(claimed: IngestionJob) -> IngestionJob:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return claimed

    worker = asyncio.create_task(
        loop_for(jobs, hang, ManualWakeups()).run(stop=asyncio.Event())
    )
    await started.wait()
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    assert cancelled.is_set()


async def test_the_lease_is_renewed_while_a_job_runs() -> None:
    jobs = CountingHeartbeats(FrozenClock())
    job = await enqueue(jobs)
    stop = asyncio.Event()
    process = sleeping(jobs, stop, seconds=0.1)

    await loop_for(jobs, process, ManualWakeups(), heartbeat_seconds=0.02).run(
        stop=stop
    )

    assert jobs.renewals >= 3
    assert (await jobs.get(job.id)).status is JobStatus.COMPLETED


async def test_a_lease_lost_during_the_job_cancels_it(
    log_stream: io.StringIO,
) -> None:
    jobs = CountingHeartbeats(FrozenClock(), outcome=LeaseLostError("taken over"))
    job = await enqueue(jobs)
    stop = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang(claimed: IngestionJob) -> IngestionJob:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            stop.set()
            raise
        return claimed

    await loop_for(jobs, hang, ManualWakeups(), heartbeat_seconds=0.01).run(stop=stop)

    assert cancelled.is_set()
    warnings = [r for r in records(log_stream) if r["level"] == "warning"]
    assert warnings[0]["job_id"] == str(job.id)
    assert "lease lost" in str(warnings[0]["message"])


async def test_a_transient_heartbeat_failure_does_not_stop_the_job() -> None:
    jobs = CountingHeartbeats(
        FrozenClock(), outcome=StorageUnavailableError("database restarting")
    )
    job = await enqueue(jobs)
    stop = asyncio.Event()
    process = sleeping(jobs, stop, seconds=0.05)

    await loop_for(jobs, process, ManualWakeups(), heartbeat_seconds=0.01).run(
        stop=stop
    )

    assert jobs.renewals >= 2
    assert (await jobs.get(job.id)).status is JobStatus.COMPLETED


async def test_the_worker_returns_after_its_job_budget_to_be_restarted(
    log_stream: io.StringIO,
) -> None:
    jobs = InMemoryJobQueue(FrozenClock())
    queued = [await enqueue(jobs) for _ in range(3)]
    never_set = asyncio.Event()

    await loop_for(
        jobs, completing(jobs, never_set, after=99), ManualWakeups(), max_jobs=2
    ).run(stop=never_set)

    statuses = [(await jobs.get(job.id)).status for job in queued]
    assert statuses == [JobStatus.COMPLETED, JobStatus.COMPLETED, JobStatus.PENDING]
    assert any("2 jobs" in str(r["message"]) for r in records(log_stream))
