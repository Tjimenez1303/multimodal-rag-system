"""Load a backlog of PDFs and measure how the API answers meanwhile (SC-006).

Run it by hand against a running system. It is not part of CI, because it needs the
whole stack and a real sample document::

    uv run --directory backend python -m tests.load.upload_backlog SAMPLE.pdf \\
        --base-url http://127.0.0.1:8000 --copies 100

Every upload is a distinct document: a copy of the sample with a PDF comment appended,
labelled with a run id, so repeated runs never hit documents already ingested. The run
has four phases:

1. ``baseline``: sequential uploads before the backlog is loaded.
2. ``backlog``: ``--copies`` uploads, ``--concurrency`` of them in flight at once.
3. ``probe``: sequential uploads, then rounds of status checks of every job, for
   ``--status-seconds``, while the backlog is queued.
4. ``drain``, with ``--wait``: waits until every job finishes and reports the total
   processing time from the jobs' own timestamps.

The report gives the p50, p95 and maximum latency of each phase, plus timeouts and
unexpected answers.
"""

import argparse
import asyncio
import logging
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/api/v1/documents"
JOB_PATH = "/api/v1/jobs/{job_id}"
FINISHED = frozenset({"completed", "failed"})
# SC-006: 95% of uploads and status checks complete in under 2 seconds.
TARGET_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Latency percentiles of one group of requests, in seconds.

    Attributes:
        count: Requests that got an answer.
        p50: Median latency.
        p95: 95th percentile latency.
        maximum: Slowest latency.
    """

    count: int
    p50: float
    p95: float
    maximum: float


@dataclass
class Phase:
    """Latencies and failures of the requests of one phase.

    Attributes:
        name: Phase shown in the report.
        latencies: Seconds each answered request took.
        timeouts: Requests that got no answer within the client timeout.
        failures: Requests that failed in transport or got an unexpected status.
    """

    name: str
    latencies: list[float] = field(default_factory=list)
    timeouts: int = 0
    failures: int = 0


def distinct_copy(content: bytes, *, run_id: str, number: int) -> bytes:
    """Return a copy of a PDF whose bytes, and so its fingerprint, are unique.

    A comment after the end-of-file marker changes the bytes without changing what
    PDF readers parse.

    Args:
        content: The original PDF.
        run_id: Identifier of the load run, so separate runs never share a copy.
        number: Number of the copy within the run.

    Returns:
        The original bytes followed by a comment line naming the run and the copy.
    """
    return content + f"\n%load-copy {run_id} {number}\n".encode()


def summarize(latencies: Sequence[float]) -> LatencySummary:
    """Compute the median, the 95th percentile and the maximum of some latencies.

    Percentiles interpolate linearly between the measured samples, treating the
    fastest and slowest samples as the 0th and 100th percentiles.

    Args:
        latencies: At least one latency, in seconds.

    Returns:
        The summary of the latencies.

    Raises:
        statistics.StatisticsError: If ``latencies`` is empty.
    """
    cuts = statistics.quantiles(latencies, n=100, method="inclusive")
    return LatencySummary(
        count=len(latencies), p50=cuts[49], p95=cuts[94], maximum=max(latencies)
    )


def makespan(jobs: Iterable[Mapping[str, Any]]) -> timedelta:
    """Time from the first job created to the last job finished.

    Both timestamps come from the server, so polling delays do not count.

    Args:
        jobs: Finished jobs as the status endpoint returns them.

    Returns:
        The total processing time of the batch.
    """
    jobs = list(jobs)
    created = min(datetime.fromisoformat(job["created_at"]) for job in jobs)
    finished = max(datetime.fromisoformat(job["finished_at"]) for job in jobs)
    return finished - created


class LoadRun:
    """Uploads distinct copies of a sample and times every request.

    Args:
        client: Client with the API base URL and the request timeout.
        sample: The PDF to copy.
        concurrency: Requests in flight at once in the concurrent phases.
    """

    def __init__(
        self, client: httpx.AsyncClient, sample: Path, *, concurrency: int
    ) -> None:
        self._client = client
        self._sample = sample
        self._content = sample.read_bytes()
        self._run_id = uuid.uuid4().hex[:8]
        self._slots = asyncio.Semaphore(concurrency)
        self._copies = 0
        self.job_ids: list[str] = []

    async def upload(self, phase: Phase, *, count: int, concurrent: bool) -> None:
        """Upload ``count`` new copies of the sample.

        Args:
            phase: Phase that records the latencies.
            count: Copies to upload.
            concurrent: Whether uploads overlap, up to the concurrency limit.
        """
        if not concurrent:
            for _ in range(count):
                await self._upload_one(phase)
            return
        async with asyncio.TaskGroup() as group:
            for _ in range(count):
                group.create_task(self._limited(self._upload_one(phase)))

    async def check_statuses(self, phase: Phase) -> list[dict[str, Any]]:
        """Read the status of every job uploaded so far, concurrently.

        Args:
            phase: Phase that records the latencies.

        Returns:
            The jobs that answered.
        """
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(self._limited(self._job(phase, job_id)))
                for job_id in self.job_ids
            ]
        return [job for task in tasks if (job := task.result()) is not None]

    async def _limited[T](self, request: Awaitable[T]) -> T:
        # The wait for a free slot is not part of the measured latency.
        async with self._slots:
            return await request

    async def _upload_one(self, phase: Phase) -> None:
        number = self._copies
        self._copies += 1
        content = distinct_copy(self._content, run_id=self._run_id, number=number)
        name = f"{self._sample.stem}-{self._run_id}-{number}.pdf"
        response = await _timed(
            phase,
            self._client.post(UPLOAD_PATH, files={"file": (name, content)}),
            expected=202,
        )
        if response is not None:
            self.job_ids.append(str(response.json()["job_id"]))

    async def _job(self, phase: Phase, job_id: str) -> dict[str, Any] | None:
        response = await _timed(
            phase, self._client.get(JOB_PATH.format(job_id=job_id)), expected=200
        )
        if response is None:
            return None
        job: dict[str, Any] = response.json()
        return job


async def _timed(
    phase: Phase, request: Awaitable[httpx.Response], *, expected: int
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await request
    except httpx.TimeoutException:
        phase.timeouts += 1
        return None
    except httpx.TransportError as error:
        logger.warning("%s request failed: %s", phase.name, error)
        phase.failures += 1
        return None
    phase.latencies.append(time.perf_counter() - started)
    if response.status_code != expected:
        logger.warning("%s answered %s", phase.name, response.status_code)
        phase.failures += 1
        return None
    return response


async def _probe(run: LoadRun, args: argparse.Namespace) -> list[Phase]:
    uploads = Phase("upload: probe")
    statuses = Phase("status: probe")
    jobs = await run.check_statuses(statuses)
    queued = sum(job["status"] in {"pending", "processing"} for job in jobs)
    logger.info("probing with %s jobs pending or processing", queued)
    await run.upload(uploads, count=args.probe_uploads, concurrent=False)
    deadline = time.monotonic() + args.status_seconds
    while time.monotonic() < deadline:
        await run.check_statuses(statuses)
    return [uploads, statuses]


async def _drain(run: LoadRun, poll_seconds: float) -> list[dict[str, Any]]:
    unmeasured = Phase("drain")
    while True:
        jobs = await run.check_statuses(unmeasured)
        done = [job for job in jobs if job["status"] in FINISHED]
        logger.info("%s of %s jobs finished", len(done), len(run.job_ids))
        if len(done) == len(run.job_ids):
            return done
        await asyncio.sleep(poll_seconds)


async def _run(args: argparse.Namespace) -> None:
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        run = LoadRun(client, args.sample, concurrency=args.concurrency)
        baseline = Phase("upload: baseline")
        await run.upload(baseline, count=args.baseline, concurrent=False)
        backlog = Phase("upload: backlog")
        await run.upload(backlog, count=args.copies, concurrent=True)
        logger.info("backlog of %s documents uploaded", len(run.job_ids))
        phases = [baseline, backlog, *await _probe(run, args)]
        _report(phases)
        if args.wait:
            jobs = await _drain(run, args.poll_seconds)
            completed = sum(job["status"] == "completed" for job in jobs)
            sys.stdout.write(
                f"\n{len(jobs)} jobs, {completed} completed, "
                f"total processing time {makespan(jobs)}\n"
            )


def _report(phases: Sequence[Phase]) -> None:
    lines = [
        f"{'phase':<18}{'count':>7}{'p50 s':>9}{'p95 s':>9}{'max s':>9}"
        f"{'timeouts':>10}{'failures':>10}  p95 < {TARGET_SECONDS:g} s"
    ]
    for phase in phases:
        if not phase.latencies:
            lines.append(f"{phase.name:<18}{0:>7}")
            continue
        summary = summarize(phase.latencies)
        met = summary.p95 < TARGET_SECONDS and phase.timeouts == 0
        lines.append(
            f"{phase.name:<18}{summary.count:>7}{summary.p50:>9.3f}"
            f"{summary.p95:>9.3f}{summary.maximum:>9.3f}{phase.timeouts:>10}"
            f"{phase.failures:>10}  {'yes' if met else 'no'}"
        )
    sys.stdout.write("\n".join(lines) + "\n")


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.load.upload_backlog",
        description="Measure the API while a backlog of PDFs is queued.",
    )
    parser.add_argument("sample", type=Path, help="PDF to upload copies of")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--copies", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--baseline", type=int, default=10)
    parser.add_argument("--probe-uploads", type=int, default=20)
    parser.add_argument("--status-seconds", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--wait", action="store_true", help="wait for every job")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the load and write the report to standard output.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            ``sys.argv[1:]``.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # httpx logs every request at INFO, which would bury the progress lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_run(_arguments(argv)))


if __name__ == "__main__":
    main()
