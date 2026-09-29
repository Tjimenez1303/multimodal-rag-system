import uuid

import pytest

from multimodal_rag.ingestion.domain import JobStage, JobStatus
from multimodal_rag.ingestion.errors import JobNotFoundError
from multimodal_rag.ingestion.use_cases.intake import GetJob
from tests.fakes import (
    FrozenClock,
    InMemoryJobQueue,
    claim_next,
    finish_next,
    pending_job,
)


@pytest.fixture
def jobs() -> InMemoryJobQueue:
    return InMemoryJobQueue(FrozenClock())


async def test_unknown_job_raises_not_found(jobs: InMemoryJobQueue) -> None:
    with pytest.raises(JobNotFoundError):
        await GetJob(jobs=jobs)(uuid.uuid4())


async def test_pending_job_reports_no_progress(jobs: InMemoryJobQueue) -> None:
    job, _ = await jobs.enqueue(pending_job(jobs.clock))

    found = await GetJob(jobs=jobs)(job.id)

    assert found.status is JobStatus.PENDING
    assert (found.stage, found.pages_done, found.pages_total) == (None, 0, None)


async def test_processing_job_reports_its_stage_and_pages(
    jobs: InMemoryJobQueue,
) -> None:
    await jobs.enqueue(pending_job(jobs.clock))
    claimed = await claim_next(jobs)
    assert claimed.lease_token is not None
    await jobs.update_progress(
        job_id=claimed.id,
        lease_token=claimed.lease_token,
        stage=JobStage.EXTRACTING,
        pages_done=8,
        pages_total=71,
    )

    found = await GetJob(jobs=jobs)(claimed.id)

    assert (found.status, found.stage) == (JobStatus.PROCESSING, JobStage.EXTRACTING)
    assert (found.pages_done, found.pages_total, found.attempt) == (8, 71, 1)


async def test_completed_job_reports_its_summary(jobs: InMemoryJobQueue) -> None:
    await jobs.enqueue(pending_job(jobs.clock))
    finished = await finish_next(jobs, succeed=True, pages=71)

    found = await GetJob(jobs=jobs)(finished.id)

    assert found.status is JobStatus.COMPLETED
    assert found.summary is not None and found.summary.pages == 71
