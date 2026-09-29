import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from multimodal_rag.ingestion.domain import (
    Document,
    IngestionJob,
    JobStatus,
)
from multimodal_rag.ingestion.errors import (
    FileTooLargeError,
    InvalidFileNameError,
    PageLimitExceededError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.ingestion.use_cases.intake import SubmitDocument, UploadLimits
from tests.fakes import (
    FakePdfInspector,
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    finish_next,
)

PDF = b"%PDF-1.7\n" + b"x" * 100


async def chunks_of(data: bytes, size: int = 16) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@dataclass
class Harness:
    documents: InMemoryDocumentRepository
    jobs: InMemoryJobQueue
    blobs: InMemoryBlobStorage
    inspector: FakePdfInspector
    submit: SubmitDocument

    async def upload(self, data: bytes = PDF, name: str = "manual.pdf") -> object:
        return await self.submit(
            file_name=name, content=chunks_of(data), correlation_id="req-1"
        )


@pytest.fixture
def harness() -> Harness:
    clock = FrozenClock()
    documents = InMemoryDocumentRepository()
    jobs = InMemoryJobQueue(clock)
    blobs = InMemoryBlobStorage()
    inspector = FakePdfInspector(page_count=12)
    submit = SubmitDocument(
        documents=documents,
        jobs=jobs,
        blobs=blobs,
        inspector=inspector,
        clock=clock,
        limits=UploadLimits(max_bytes=1_000, max_pages=500),
        max_attempts=3,
    )
    return Harness(documents, jobs, blobs, inspector, submit)


async def test_new_file_creates_a_document_and_a_pending_job(harness: Harness) -> None:
    submission = await harness.submit(
        file_name="manual.pdf", content=chunks_of(PDF), correlation_id="req-7"
    )

    sha256 = hashlib.sha256(PDF).hexdigest()
    assert submission.already_ingested is False
    assert submission.document.sha256 == sha256
    assert submission.document.size_bytes == len(PDF)
    assert submission.document.page_count == 12
    assert submission.document.file_name == "manual.pdf"
    assert submission.job.status is JobStatus.PENDING
    assert submission.job.correlation_id == "req-7"
    assert submission.job.max_attempts == 3
    assert await harness.blobs.read_bytes(Document.blob_key_for(sha256)) == PDF
    assert list(harness.blobs.blobs) == [Document.blob_key_for(sha256)]
    assert harness.jobs.notifications == 1


async def test_identical_content_already_completed_is_not_processed_again(
    harness: Harness,
) -> None:
    first = await harness.submit(
        file_name="a.pdf", content=chunks_of(PDF), correlation_id="req-1"
    )
    await finish_next(harness.jobs, succeed=True)

    second = await harness.submit(
        file_name="renamed.pdf", content=chunks_of(PDF), correlation_id="req-2"
    )

    assert second.already_ingested is True
    assert second.document.id == first.document.id
    assert second.job.id == first.job.id
    assert second.job.status is JobStatus.COMPLETED
    assert len(harness.jobs.jobs) == 1


async def test_identical_content_still_processing_returns_the_same_job(
    harness: Harness,
) -> None:
    first = await harness.submit(
        file_name="a.pdf", content=chunks_of(PDF), correlation_id="req-1"
    )

    second = await harness.submit(
        file_name="a.pdf", content=chunks_of(PDF), correlation_id="req-2"
    )

    assert second.already_ingested is False
    assert (second.document.id, second.job.id) == (first.document.id, first.job.id)
    assert len(harness.jobs.jobs) == 1


async def test_identical_content_whose_last_job_failed_gets_a_new_job(
    harness: Harness,
) -> None:
    first = await harness.submit(
        file_name="a.pdf", content=chunks_of(PDF), correlation_id="req-1"
    )
    await finish_next(harness.jobs, succeed=False)

    second = await harness.submit(
        file_name="a.pdf", content=chunks_of(PDF), correlation_id="req-2"
    )

    assert second.already_ingested is False
    assert second.document.id == first.document.id
    assert second.job.id != first.job.id
    assert second.job.status is JobStatus.PENDING
    assert second.job.correlation_id == "req-2"


class StaleReadJobQueue(InMemoryJobQueue):
    """Misses the job a concurrent upload enqueued a moment before."""

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        return None


async def test_a_job_enqueued_concurrently_for_the_same_content_is_reused() -> None:
    clock = FrozenClock()
    jobs = StaleReadJobQueue(clock)
    submit = SubmitDocument(
        documents=InMemoryDocumentRepository(),
        jobs=jobs,
        blobs=InMemoryBlobStorage(),
        inspector=FakePdfInspector(),
        clock=clock,
        limits=UploadLimits(max_bytes=1_000, max_pages=500),
        max_attempts=3,
    )

    first = await submit(file_name="a.pdf", content=chunks_of(PDF), correlation_id="1")
    second = await submit(file_name="a.pdf", content=chunks_of(PDF), correlation_id="2")

    assert second.job.id == first.job.id
    assert len(jobs.jobs) == 1


async def test_non_pdf_content_is_rejected_without_a_job(harness: Harness) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        await harness.upload(b"plain text renamed to pdf")

    assert harness.jobs.jobs == {}
    assert harness.documents.documents == {}
    assert harness.blobs.blobs == {}


async def test_file_over_the_size_limit_is_rejected_without_a_job(
    harness: Harness,
) -> None:
    with pytest.raises(FileTooLargeError, match="1000 bytes"):
        await harness.upload(PDF + b"x" * 1_000)

    assert harness.jobs.jobs == {}
    assert harness.blobs.blobs == {}


async def test_file_over_the_page_limit_is_rejected_without_a_job(
    harness: Harness,
) -> None:
    harness.inspector.page_count = 501

    with pytest.raises(PageLimitExceededError, match="500 pages"):
        await harness.upload()

    assert harness.jobs.jobs == {}
    assert harness.documents.documents == {}
    assert harness.blobs.blobs == {}


async def test_encrypted_file_is_accepted_and_fails_later(harness: Harness) -> None:
    harness.inspector.encrypted = True

    submission = await harness.submit(
        file_name="locked.pdf", content=chunks_of(PDF), correlation_id="req-1"
    )

    assert submission.document.page_count is None
    assert submission.job.status is JobStatus.PENDING


@pytest.mark.parametrize("name", ["", "x" * 252 + ".pdf"])
async def test_file_names_outside_the_documented_length_are_rejected(
    harness: Harness, name: str
) -> None:
    with pytest.raises(InvalidFileNameError):
        await harness.upload(name=name)

    assert harness.blobs.blobs == {}


async def test_directory_parts_of_the_uploaded_name_are_dropped(
    harness: Harness,
) -> None:
    submission = await harness.submit(
        file_name="C:\\manuals\\pump.pdf",
        content=chunks_of(PDF),
        correlation_id="req-1",
    )

    assert submission.document.file_name == "pump.pdf"
