"""PostgreSQL job queue with row-level claims, leases and fencing tokens.

Workers claim the oldest claimable job with ``FOR UPDATE SKIP LOCKED``, so concurrent
claimers never block each other or take the same row. A job is claimable when it is
pending, or processing with a lease that expired because its worker stopped renewing
it. Each claim issues a new lease token, and every later write locks the row only when
it still carries that token, so a worker whose lease was taken over changes nothing.

Leases are measured on the database clock, the one clock every worker shares, so clock
skew between replicas cannot expire a lease early or keep a dead one alive.
"""

import dataclasses
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from multimodal_rag.adapters.postgres.engine import connect, transaction
from multimodal_rag.adapters.postgres.tables import ACTIVE_JOB_PREDICATE, ingestion_jobs
from multimodal_rag.ingestion.domain import (
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    JobSummary,
)
from multimodal_rag.ingestion.errors import JobNotFoundError, LeaseLostError
from multimodal_rag.shared.errors import DataInconsistencyError

logger = logging.getLogger(__name__)

_ACTIVE = sa.text(ACTIVE_JOB_PREDICATE)
# Each retry needs the active job to fail between two statements, so a few suffice.
_ENQUEUE_ATTEMPTS = 3
# Set when a job is created and never changed by later writes.
_IMMUTABLE_COLUMNS = frozenset(
    {"id", "document_id", "max_attempts", "correlation_id", "created_at"}
)
_SUMMARY_FIELDS = frozenset(field.name for field in dataclasses.fields(JobSummary))
_CLAIMABLE = sa.or_(
    ingestion_jobs.c.status == JobStatus.PENDING.value,
    sa.and_(
        ingestion_jobs.c.status == JobStatus.PROCESSING.value,
        ingestion_jobs.c.lease_expires_at < sa.func.now(),
    ),
)


class PostgresJobQueue:
    """Durable queue and store of ingestion jobs.

    Args:
        engine: Engine of the current process.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def enqueue(self, job: IngestionJob) -> tuple[IngestionJob, bool]:
        """Store a new pending job unless the document already has an active one.

        The insert fires the trigger that notifies idle workers. When the insert
        conflicts but the active job fails before it is read, the insert is tried
        again.

        Args:
            job: Pending job to store.

        Returns:
            The stored job and ``True``, or the document's job that has not failed
            and ``False``.

        Raises:
            DataInconsistencyError: If the conflict persists without an active job.
        """
        statement = (
            insert(ingestion_jobs)
            .values(**_values(job))
            .on_conflict_do_nothing(
                index_elements=[ingestion_jobs.c.document_id], index_where=_ACTIVE
            )
            .returning(ingestion_jobs.c.id)
        )
        async with transaction(self._engine) as connection:
            for _ in range(_ENQUEUE_ATTEMPTS):
                if (await connection.execute(statement)).scalar_one_or_none():
                    return job, True
                existing = await self._active_job(connection, job.document_id)
                if existing is not None:
                    return existing, False
        raise DataInconsistencyError(
            f"Enqueueing for document {job.document_id} conflicted with no job"
        )

    async def _active_job(
        self, connection: AsyncConnection, document_id: uuid.UUID
    ) -> IngestionJob | None:
        query = sa.select(ingestion_jobs).where(
            ingestion_jobs.c.document_id == document_id, _ACTIVE
        )
        row = (await connection.execute(query)).mappings().one_or_none()
        return None if row is None else _job(row)

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        """Return a job by id.

        Args:
            job_id: Id of the job.

        Returns:
            The stored job.

        Raises:
            JobNotFoundError: If no job has this id.
        """
        query = sa.select(ingestion_jobs).where(ingestion_jobs.c.id == job_id)
        async with connect(self._engine) as connection:
            row = (await connection.execute(query)).mappings().one_or_none()
        if row is None:
            raise JobNotFoundError(f"Job {job_id} not found")
        return _job(row)

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        """Return the most recent job of a document, if any.

        Args:
            document_id: Document whose jobs are searched.

        Returns:
            The newest job, or ``None`` when the document has none.
        """
        query = (
            sa.select(ingestion_jobs)
            .where(ingestion_jobs.c.document_id == document_id)
            .order_by(ingestion_jobs.c.created_at.desc(), ingestion_jobs.c.id.desc())
            .limit(1)
        )
        async with connect(self._engine) as connection:
            row = (await connection.execute(query)).mappings().one_or_none()
        return None if row is None else _job(row)

    async def claim(self, *, worker_id: str, lease_seconds: int) -> IngestionJob | None:
        """Claim the oldest claimable job for this worker.

        Jobs whose every allowed attempt was interrupted are failed on the way with
        ``interrupted_repeatedly``, and the next claimable job is tried.

        Args:
            worker_id: Holder of the new lease, for diagnostics.
            lease_seconds: Duration of the new lease.

        Returns:
            The claimed job in ``processing`` with a fresh lease, or ``None`` when no
            job is claimable.
        """
        candidate = (
            sa.select(ingestion_jobs)
            .where(_CLAIMABLE)
            .order_by(ingestion_jobs.c.created_at, ingestion_jobs.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        async with transaction(self._engine) as connection:
            now = await _database_now(connection)
            while row := (await connection.execute(candidate)).mappings().first():
                job = _job(row)
                if job.attempts_exhausted:
                    logger.warning(
                        "job %s failed after %s attempts", job.id, job.attempt
                    )
                    await _save(connection, job.fail_interrupted(now=now))
                    continue
                claimed = job.claim(
                    lease_token=uuid.uuid4(),
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    worker_id=worker_id,
                    now=now,
                )
                await _save(connection, claimed)
                return claimed
        return None

    async def heartbeat(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int
    ) -> None:
        """Extend the lease of a running attempt.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            lease_seconds: New lease duration from now.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        await self._fenced_update(
            job_id,
            lease_token,
            lambda job, now: dataclasses.replace(
                job,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            ),
        )

    async def update_progress(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        stage: JobStage,
        pages_done: int,
        pages_total: int | None,
    ) -> None:
        """Record the stage and page progress of a running attempt.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            stage: Step being run.
            pages_done: Pages processed so far.
            pages_total: Pages to process, when known.

        Raises:
            LeaseLostError: If the token is no longer current.
            InvalidJobTransitionError: If the progress is inconsistent.
        """
        await self._fenced_update(
            job_id,
            lease_token,
            lambda job, now: job.advance(
                stage=stage, pages_done=pages_done, pages_total=pages_total, now=now
            ),
        )

    async def complete(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, summary: JobSummary
    ) -> IngestionJob:
        """Mark a running attempt as completed.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            summary: Counts of what the job captured.

        Returns:
            The completed job.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        return await self._fenced_update(
            job_id, lease_token, lambda job, now: job.complete(summary=summary, now=now)
        )

    async def fail(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        code: FailureCode,
        reason: str,
    ) -> IngestionJob:
        """Mark a running attempt as failed.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            code: Machine-readable cause.
            reason: Human-readable reason without document content.

        Returns:
            The failed job.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        return await self._fenced_update(
            job_id,
            lease_token,
            lambda job, now: job.fail(code=code, reason=reason, now=now),
        )

    async def _fenced_update(
        self,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        change: Callable[[IngestionJob, datetime], IngestionJob],
    ) -> IngestionJob:
        async with transaction(self._engine) as connection:
            job = await lock_leased_job(connection, job_id, lease_token)
            changed = change(job, await _database_now(connection))
            await _save(connection, changed)
        return changed


async def lock_leased_job(
    connection: AsyncConnection, job_id: uuid.UUID, lease_token: uuid.UUID
) -> IngestionJob:
    """Lock a job row for the rest of the transaction if the lease is still held.

    Holding the row lock while writing makes a concurrent claim wait, so a write can
    never interleave with a takeover.

    Args:
        connection: Connection inside an open transaction.
        job_id: Job being written.
        lease_token: Token of the attempt that writes.

    Returns:
        The job as stored.

    Raises:
        LeaseLostError: If the job no longer carries this token.
    """
    query = (
        sa.select(ingestion_jobs)
        .where(
            ingestion_jobs.c.id == job_id, ingestion_jobs.c.lease_token == lease_token
        )
        .with_for_update()
    )
    row = (await connection.execute(query)).mappings().one_or_none()
    if row is None:
        raise LeaseLostError(f"Lease of job {job_id} is no longer held")
    return _job(row)


async def _database_now(connection: AsyncConnection) -> datetime:
    # Start time of the current transaction, the same for every statement in it.
    now = await connection.scalar(sa.select(sa.func.now()))
    if not isinstance(now, datetime):
        raise DataInconsistencyError("The database did not return its current time")
    return now


async def _save(connection: AsyncConnection, job: IngestionJob) -> None:
    values = {
        name: value
        for name, value in _values(job).items()
        if name not in _IMMUTABLE_COLUMNS
    }
    await connection.execute(
        sa.update(ingestion_jobs).where(ingestion_jobs.c.id == job.id).values(**values)
    )


def _values(job: IngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "document_id": job.document_id,
        "status": job.status.value,
        "stage": None if job.stage is None else job.stage.value,
        "pages_total": job.pages_total,
        "pages_done": job.pages_done,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "lease_token": job.lease_token,
        "lease_expires_at": job.lease_expires_at,
        "worker_id": job.worker_id,
        "correlation_id": job.correlation_id,
        "failure_code": None if job.failure_code is None else job.failure_code.value,
        "failure_reason": job.failure_reason,
        "summary": None if job.summary is None else dataclasses.asdict(job.summary),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "updated_at": job.updated_at,
    }


def _job(row: sa.RowMapping) -> IngestionJob:
    return IngestionJob(
        id=row["id"],
        document_id=row["document_id"],
        status=JobStatus(row["status"]),
        max_attempts=row["max_attempts"],
        correlation_id=row["correlation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        stage=None if row["stage"] is None else JobStage(row["stage"]),
        pages_total=row["pages_total"],
        pages_done=row["pages_done"],
        attempt=row["attempt"],
        lease_token=row["lease_token"],
        lease_expires_at=row["lease_expires_at"],
        worker_id=row["worker_id"],
        failure_code=(
            None if row["failure_code"] is None else FailureCode(row["failure_code"])
        ),
        failure_reason=row["failure_reason"],
        summary=None if row["summary"] is None else _summary(row["summary"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _summary(stored: dict[str, Any]) -> JobSummary:
    # Rows written by an older or newer release may carry other counts.
    return JobSummary(**{k: v for k, v in stored.items() if k in _SUMMARY_FIELDS})
