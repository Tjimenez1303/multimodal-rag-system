"""Intake of uploads and tracking of their jobs, served by the REST API."""

import asyncio
import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass

from multimodal_rag.ingestion.domain import (
    MAX_FILE_NAME_LENGTH,
    Document,
    IngestionJob,
    JobStatus,
)
from multimodal_rag.ingestion.errors import (
    FileTooLargeError,
    InvalidFileNameError,
    PageLimitExceededError,
)
from multimodal_rag.ingestion.ports import (
    BlobStorage,
    Clock,
    DocumentRepository,
    JobQueue,
    PdfInspector,
)

logger = logging.getLogger(__name__)

_PATH_SEPARATORS = re.compile(r"[\\/]")


@dataclass(frozen=True, slots=True)
class UploadLimits:
    """Largest upload the system accepts.

    Attributes:
        max_bytes: Largest file size in bytes.
        max_pages: Largest page count.
    """

    max_bytes: int
    max_pages: int


@dataclass(frozen=True, slots=True)
class Submission:
    """Outcome of an upload.

    Attributes:
        document: The new document, or the existing one with identical content.
        job: The job that ingests the document.
        already_ingested: Whether identical content had already completed, so no
            processing happens.
    """

    document: Document
    job: IngestionJob
    already_ingested: bool


@dataclass(frozen=True, slots=True)
class _StoredFile:
    sha256: str
    size_bytes: int
    page_count: int | None


class SubmitDocument:
    """Stores an uploaded PDF, registers it by fingerprint and enqueues its job.

    Args:
        documents: Document persistence.
        jobs: Job queue.
        blobs: Storage of the original files.
        inspector: Cheap PDF checks run before a job exists.
        clock: Source of the current time.
        limits: Size and page limits of an upload.
        max_attempts: Attempts allowed for each new job.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobQueue,
        blobs: BlobStorage,
        inspector: PdfInspector,
        clock: Clock,
        limits: UploadLimits,
        max_attempts: int,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._blobs = blobs
        self._inspector = inspector
        self._clock = clock
        self._limits = limits
        self._max_attempts = max_attempts

    async def __call__(
        self, *, file_name: str, content: AsyncIterable[bytes], correlation_id: str
    ) -> Submission:
        """Accept an upload without processing its content.

        Args:
            file_name: Name sent by the client. Directory parts are dropped.
            content: File bytes in order.
            correlation_id: Request id stored on a new job.

        Returns:
            The document and its job. Identical content that completed or is still
            being processed returns the existing job, and content whose last job
            failed gets a new one.

        Raises:
            InvalidFileNameError: If the name is empty, too long or not printable.
            FileTooLargeError: If the file exceeds the size limit.
            UnsupportedMediaTypeError: If the file is not a PDF by content.
            PageLimitExceededError: If the PDF exceeds the page limit.
        """
        name = _base_name(file_name)
        stored = await self._store(content)
        document, _ = await self._documents.register(
            Document(
                id=uuid.uuid4(),
                sha256=stored.sha256,
                file_name=name,
                size_bytes=stored.size_bytes,
                page_count=stored.page_count,
                blob_key=Document.blob_key_for(stored.sha256),
                created_at=self._clock.now(),
            )
        )
        submission = await self._job_for(document, correlation_id=correlation_id)
        logger.info(
            "document %s uploaded, job %s, %s bytes, %s pages, already ingested %s",
            document.id,
            submission.job.id,
            stored.size_bytes,
            stored.page_count,
            submission.already_ingested,
        )
        return submission

    async def _store(self, content: AsyncIterable[bytes]) -> _StoredFile:
        # The file lands under a staging key first, so a rejected upload never
        # reaches its content-addressed key.
        digest = hashlib.sha256()
        staging_key = f"uploads/{uuid.uuid4().hex}.pdf"
        try:
            size = await self._blobs.save_stream(
                staging_key, self._limited(content, digest.update)
            )
            page_count = await self._checked_page_count(staging_key)
            await self._blobs.move(
                staging_key, Document.blob_key_for(digest.hexdigest())
            )
        except BaseException:
            await self._blobs.delete(staging_key)
            raise
        return _StoredFile(digest.hexdigest(), size, page_count)

    async def _limited(
        self, content: AsyncIterable[bytes], update: Callable[[bytes], object]
    ) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in content:
            size += len(chunk)
            if size > self._limits.max_bytes:
                raise FileTooLargeError(
                    f"The file exceeds the upload limit of "
                    f"{self._limits.max_bytes} bytes"
                )
            # hashlib releases the GIL for large chunks, so hashing in a thread keeps
            # the event loop free for other requests.
            await asyncio.to_thread(update, chunk)
            yield chunk

    async def _checked_page_count(self, key: str) -> int | None:
        with self._blobs.materialize(key) as path:
            info = await asyncio.to_thread(self._inspector.inspect, path)
        if info.page_count is not None and info.page_count > self._limits.max_pages:
            raise PageLimitExceededError(
                f"The PDF has {info.page_count} pages, more than the limit of "
                f"{self._limits.max_pages} pages"
            )
        return info.page_count

    async def _job_for(self, document: Document, *, correlation_id: str) -> Submission:
        job = await self._jobs.latest_for_document(document.id)
        if job is None or job.status is JobStatus.FAILED:
            job, _ = await self._jobs.enqueue(
                IngestionJob.create(
                    job_id=uuid.uuid4(),
                    document_id=document.id,
                    max_attempts=self._max_attempts,
                    correlation_id=correlation_id,
                    now=self._clock.now(),
                )
            )
        return Submission(
            document=document,
            job=job,
            already_ingested=job.status is JobStatus.COMPLETED,
        )


def _base_name(file_name: str) -> str:
    name = _PATH_SEPARATORS.split(file_name)[-1].strip()
    # PostgreSQL text cannot hold NUL, and control characters break log lines.
    if not 0 < len(name) <= MAX_FILE_NAME_LENGTH or not name.isprintable():
        raise InvalidFileNameError(
            f"The file name must have 1 to {MAX_FILE_NAME_LENGTH} printable characters"
        )
    return name


class GetJob:
    """Returns the current state and progress of a job.

    Args:
        jobs: Job queue.
    """

    def __init__(self, *, jobs: JobQueue) -> None:
        self._jobs = jobs

    async def __call__(self, job_id: uuid.UUID) -> IngestionJob:
        """Return a job by id.

        Args:
            job_id: Id returned by the upload.

        Returns:
            The job with its state, stage and page progress.

        Raises:
            JobNotFoundError: If no job has this id.
        """
        return await self._jobs.get(job_id)
