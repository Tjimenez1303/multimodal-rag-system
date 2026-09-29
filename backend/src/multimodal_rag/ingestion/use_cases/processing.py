"""Processing of claimed jobs, run by the worker."""

import asyncio
import logging
import uuid

from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobSummary,
)
from multimodal_rag.ingestion.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    JobNotLeasedError,
    LeaseLostError,
    NoExtractableTextError,
)
from multimodal_rag.ingestion.ports import (
    BlobStorage,
    DocumentExtractor,
    DocumentRepository,
    ElementRepository,
    ExtractionBatch,
    JobQueue,
)
from multimodal_rag.shared.errors import (
    ExtractionError,
    StorageTimeoutError,
    StorageUnavailableError,
)

logger = logging.getLogger(__name__)

_TEXT_KINDS = frozenset(
    {
        ElementKind.HEADING,
        ElementKind.PARAGRAPH,
        ElementKind.LIST_ITEM,
        ElementKind.CAPTION,
    }
)
_NON_TEXT_KINDS = frozenset({ElementKind.IMAGE, ElementKind.PAGE_FURNITURE})
_FAILURE_BY_ERROR: dict[type[ExtractionError], FailureCode] = {
    EncryptedDocumentError: FailureCode.ENCRYPTED_DOCUMENT,
    CorruptDocumentError: FailureCode.CORRUPT_DOCUMENT,
    NoExtractableTextError: FailureCode.NO_EXTRACTABLE_TEXT,
}
# Shown to clients, so they describe the cause and never quote document content.
_FAILURE_REASONS = {
    FailureCode.ENCRYPTED_DOCUMENT: "The PDF is password protected or encrypted.",
    FailureCode.CORRUPT_DOCUMENT: "The PDF is damaged and cannot be read.",
    FailureCode.NO_EXTRACTABLE_TEXT: "No text could be read or recognized on any page.",
    FailureCode.INTERNAL_ERROR: "Processing failed because of an internal error.",
}


class ProcessJob:
    """Runs one claimed attempt of a job: extraction, then finalization.

    Every write carries the attempt's lease token, so a worker whose lease was taken
    over stops at its next write and changes nothing.

    Args:
        documents: Document persistence.
        jobs: Job queue.
        elements: Element persistence.
        blobs: Storage of the original files and figure crops.
        extractor: Layout-aware extraction of typed elements.
        page_batch: Pages extracted per batch.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobQueue,
        elements: ElementRepository,
        blobs: BlobStorage,
        extractor: DocumentExtractor,
        page_batch: int,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._elements = elements
        self._blobs = blobs
        self._extractor = extractor
        self._page_batch = page_batch

    async def __call__(self, job: IngestionJob) -> IngestionJob:
        """Process a claimed job until it completes or fails.

        Args:
            job: A job claimed by this worker, carrying its lease token.

        Returns:
            The job in ``completed`` or ``failed``.

        Raises:
            JobNotLeasedError: If the job carries no lease token.
            LeaseLostError: If another worker took the job over.
            StorageUnavailableError: If the database is unreachable.
            StorageTimeoutError: If the database does not answer in time.
        """
        if job.lease_token is None:
            raise JobNotLeasedError(f"Job {job.id} was not claimed")
        lease_token = job.lease_token
        try:
            summary = await self._run(job, lease_token)
        except LeaseLostError, StorageUnavailableError, StorageTimeoutError:
            # Not the document's fault: the attempt is abandoned without failing the
            # job, and the job keeps its processing state and its lease.
            raise
        except ExtractionError as error:
            code = _FAILURE_BY_ERROR.get(type(error), FailureCode.INTERNAL_ERROR)
            logger.warning("job failed with %s", code)
            return await self._fail(job, lease_token, code)
        except Exception:  # any other failure must still end the job, never hang it
            logger.exception("job failed with an internal error")
            return await self._fail(job, lease_token, FailureCode.INTERNAL_ERROR)
        finished = await self._jobs.complete(
            job_id=job.id, lease_token=lease_token, summary=summary
        )
        logger.info("job completed, %s pages", summary.pages)
        return finished

    async def _run(self, job: IngestionJob, lease_token: uuid.UUID) -> JobSummary:
        document = await self._documents.get(job.document_id)
        logger.info("job started, attempt %s, document %s", job.attempt, document.id)
        elements, pages, recognized = await self._extract(document, job, lease_token)
        if not any(_has_text(element) for element in elements):
            raise NoExtractableTextError(f"Document {document.id} yields no text")
        await self._progress(job, lease_token, JobStage.FINALIZING, pages, pages)
        await self._elements.replace_for_document(
            job_id=job.id,
            lease_token=lease_token,
            document_id=document.id,
            elements=elements,
            relationships=(),
        )
        return JobSummary(
            pages=pages,
            text_elements=sum(e.kind in _TEXT_KINDS for e in elements),
            tables=sum(e.kind is ElementKind.TABLE for e in elements),
            images=sum(e.kind is ElementKind.IMAGE for e in elements),
            recognized_pages=len(recognized),
        )

    async def _extract(
        self, document: Document, job: IngestionJob, lease_token: uuid.UUID
    ) -> tuple[list[ExtractedElement], int, set[int]]:
        elements: list[ExtractedElement] = []
        recognized: set[int] = set()
        pages_total = document.page_count
        await self._progress(job, lease_token, JobStage.EXTRACTING, 0, pages_total)
        with self._blobs.materialize(document.blob_key) as path:
            batches = self._extractor.extract(
                path=path,
                document_id=document.id,
                document_sha256=document.sha256,
                batch_size=self._page_batch,
            )
            # Extraction blocks on CPU, so each batch runs in a worker thread.
            while (batch := await asyncio.to_thread(next, batches, None)) is not None:
                elements += await self._store_images(batch)
                recognized.update(batch.recognized_pages)
                pages_total = batch.pages_total
                await self._progress(
                    job, lease_token, JobStage.EXTRACTING, batch.last_page, pages_total
                )
        return elements, pages_total or 0, recognized

    async def _store_images(self, batch: ExtractionBatch) -> list[ExtractedElement]:
        stored = []
        for element in batch.elements:
            png = batch.images.get(element.id)
            if png is not None:
                key = ExtractedElement.image_key_for(
                    document_id=element.document_id, element_id=element.id
                )
                await self._blobs.save_bytes(key, png)
                element = element.with_image_key(key)
            stored.append(element)
        return stored

    async def _progress(
        self,
        job: IngestionJob,
        lease_token: uuid.UUID,
        stage: JobStage,
        pages_done: int,
        pages_total: int | None,
    ) -> None:
        await self._jobs.update_progress(
            job_id=job.id,
            lease_token=lease_token,
            stage=stage,
            pages_done=pages_done,
            pages_total=pages_total,
        )

    async def _fail(
        self, job: IngestionJob, lease_token: uuid.UUID, code: FailureCode
    ) -> IngestionJob:
        return await self._jobs.fail(
            job_id=job.id,
            lease_token=lease_token,
            code=code,
            reason=_FAILURE_REASONS[code],
        )


def _has_text(element: ExtractedElement) -> bool:
    return element.kind not in _NON_TEXT_KINDS and bool(
        element.text and element.text.strip()
    )
