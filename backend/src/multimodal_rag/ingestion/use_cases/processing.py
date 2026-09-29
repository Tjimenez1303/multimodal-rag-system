"""Processing of claimed jobs, run by the worker."""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from functools import partial

from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobSummary,
    PageSize,
    RelationshipKind,
    RetrievalUnit,
)
from multimodal_rag.ingestion.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    LeaseLostError,
    NoExtractableTextError,
    ServiceFailedError,
)
from multimodal_rag.ingestion.figures import (
    FigurePolicy,
    description_context,
    unverified_identifiers,
)
from multimodal_rag.ingestion.ports import (
    BlobStorage,
    DocumentExtractor,
    DocumentRepository,
    ElementRepository,
    Embedder,
    ExtractionBatch,
    FigureDescriber,
    JobQueue,
    TokenCounter,
    VectorIndex,
)
from multimodal_rag.ingestion.relationships import link_elements
from multimodal_rag.ingestion.retrieval_units import build_units
from multimodal_rag.shared.errors import (
    ExtractionError,
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StorageTimeoutError,
    StorageUnavailableError,
)

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "embedding model"
VECTOR_INDEX = "vector index"
_TEXT_KINDS = frozenset(
    {
        ElementKind.HEADING,
        ElementKind.PARAGRAPH,
        ElementKind.LIST_ITEM,
        ElementKind.CAPTION,
    }
)
_NON_TEXT_KINDS = frozenset({ElementKind.IMAGE, ElementKind.PAGE_FURNITURE})
_UNREACHABLE = (ProviderUnavailableError, ProviderTimeoutError)
_CONTINUES = RelationshipKind.CONTINUES
# Records the stage of a running attempt, keeping its page progress.
type _Stage = Callable[[JobStage], Awaitable[None]]
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


@dataclass(frozen=True, slots=True)
class EnrichmentOptions:
    """Settings of the stages that follow extraction.

    Attributes:
        figure_policy: Rules that pick decorative figures and the ones to describe.
        figure_concurrency: Figures described at the same time.
        near_text_max_points: Largest gap between a figure and its nearby text.
        max_unit_tokens: Token ceiling of a text unit.
        embedder_max_input_tokens: Longest input the embedding model accepts.
    """

    figure_policy: FigurePolicy
    figure_concurrency: int
    near_text_max_points: float
    max_unit_tokens: int
    embedder_max_input_tokens: int


@dataclass
class _Extraction:
    elements: list[ExtractedElement] = field(default_factory=list)
    links: list[ElementRelationship] = field(default_factory=list)
    page_sizes: dict[int, PageSize] = field(default_factory=dict)
    image_hashes: dict[uuid.UUID, str] = field(default_factory=dict)
    recognized: set[int] = field(default_factory=set)
    pages: int = 0


class ProcessJob:
    """Runs one claimed attempt of a job, from extraction to indexing.

    Every write to the job store carries the attempt's lease token, so a worker whose
    lease was taken over stops at its next write. Each attempt starts by deleting the
    document's points and publishes them only once the elements are stored, so a
    failed or interrupted attempt leaves nothing searchable.

    Args:
        documents: Document persistence.
        jobs: Job queue.
        elements: Element persistence.
        blobs: Storage of the original files and figure crops.
        extractor: Layout-aware extraction of typed elements.
        describer: Vision model, or ``None`` when figure description is disabled.
        embedder: Embedding model.
        token_counter: Tokenizer of the embedding model.
        index: Hybrid index of retrieval units.
        page_batch: Pages extracted per batch.
        enrichment: Settings of the stages that follow extraction.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobQueue,
        elements: ElementRepository,
        blobs: BlobStorage,
        extractor: DocumentExtractor,
        describer: FigureDescriber | None,
        embedder: Embedder,
        token_counter: TokenCounter,
        index: VectorIndex,
        page_batch: int,
        enrichment: EnrichmentOptions,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._elements = elements
        self._blobs = blobs
        self._extractor = extractor
        self._describer = describer
        self._embedder = embedder
        self._tokens = token_counter
        self._index = index
        self._page_batch = page_batch
        self._options = enrichment

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
        lease_token = job.held_lease()
        try:
            summary = await self._run(job, lease_token)
        except LeaseLostError, StorageUnavailableError, StorageTimeoutError:
            # Not the document's fault: the attempt is abandoned without failing the
            # job, and the next attempt deletes whatever this one indexed.
            raise
        except ServiceFailedError as error:
            logger.warning("job failed because the %s failed", error.service)
            if error.transient:
                reason = f"The {error.service} was unavailable after its retries."
                code = FailureCode.PROVIDER_UNAVAILABLE
            else:
                reason = f"The {error.service} rejected a request."
                code = FailureCode.INTERNAL_ERROR
            return await self._fail(job, lease_token, code, reason)
        except ExtractionError as error:
            code = _FAILURE_BY_ERROR.get(type(error), FailureCode.INTERNAL_ERROR)
            logger.warning("job failed with %s", code)
            return await self._fail(job, lease_token, code, _FAILURE_REASONS[code])
        except Exception:  # any other failure must still end the job, never hang it
            logger.exception("job failed with an internal error")
            code = FailureCode.INTERNAL_ERROR
            return await self._fail(job, lease_token, code, _FAILURE_REASONS[code])
        finished = await self._jobs.complete(
            job_id=job.id, lease_token=lease_token, summary=summary
        )
        logger.info("job completed, %s pages", summary.pages)
        return finished

    async def _run(self, job: IngestionJob, lease_token: uuid.UUID) -> JobSummary:
        document = await self._documents.get(job.document_id)
        logger.info("job started, attempt %s, document %s", job.attempt, document.id)
        await _using(VECTOR_INDEX, self._index.delete_document(document.id))
        extraction = await self._extract(document, job, lease_token)
        if not any(_has_text(element) for element in extraction.elements):
            raise NoExtractableTextError(f"Document {document.id} yields no text")
        pages = extraction.pages
        # Every later stage keeps the page progress extraction reached.
        stage = partial(
            self._progress, job, lease_token, pages_done=pages, pages_total=pages
        )
        await stage(JobStage.DESCRIBING_FIGURES)
        triage = self._options.figure_policy.triage(
            extraction.elements,
            image_hashes=extraction.image_hashes,
            page_sizes=extraction.page_sizes,
            pages_total=pages,
            describe=self._describer is not None,
        )
        links = link_elements(
            triage.elements,
            page_sizes=extraction.page_sizes,
            extracted=extraction.links,
            near_max_points=self._options.near_text_max_points,
        )
        elements = await self._describe(triage.elements, triage.to_describe, links)
        units = await self._index_units(document, elements, links, stage)
        await stage(JobStage.FINALIZING)
        await self._elements.replace_for_document(
            job_id=job.id,
            lease_token=lease_token,
            document_id=document.id,
            elements=elements,
            relationships=links,
        )
        await _using(VECTOR_INDEX, self._index.publish(document.id))
        return _summary(extraction, elements, links, units)

    async def _extract(
        self, document: Document, job: IngestionJob, lease_token: uuid.UUID
    ) -> _Extraction:
        extraction = _Extraction(pages=document.page_count or 0)
        await self._progress(
            job, lease_token, JobStage.EXTRACTING, 0, document.page_count
        )
        with self._blobs.materialize(document.blob_key) as path:
            batches = self._extractor.extract(
                path=path,
                document_id=document.id,
                document_sha256=document.sha256,
                batch_size=self._page_batch,
            )
            # Extraction blocks on CPU, so each batch runs in a worker thread.
            while (batch := await asyncio.to_thread(next, batches, None)) is not None:
                await self._collect(batch, extraction)
                await self._progress(
                    job,
                    lease_token,
                    JobStage.EXTRACTING,
                    batch.last_page,
                    batch.pages_total,
                )
        return extraction

    async def _collect(self, batch: ExtractionBatch, extraction: _Extraction) -> None:
        for element in batch.elements:
            png = batch.images.get(element.id)
            if png is not None:
                key = ExtractedElement.image_key_for(
                    document_id=element.document_id, element_id=element.id
                )
                await self._blobs.save_bytes(key, png)
                extraction.image_hashes[element.id] = hashlib.sha256(png).hexdigest()
                element = element.with_image_key(key)
            extraction.elements.append(element)
        extraction.links += batch.relationships
        extraction.page_sizes |= batch.page_sizes
        extraction.recognized.update(batch.recognized_pages)
        extraction.pages = batch.pages_total

    async def _describe(
        self,
        elements: Sequence[ExtractedElement],
        chosen: Sequence[uuid.UUID],
        links: Sequence[ElementRelationship],
    ) -> list[ExtractedElement]:
        by_id = {element.id: element for element in elements}
        if self._describer is None or not chosen:
            return list(elements)
        describer = self._describer
        slots = asyncio.Semaphore(self._options.figure_concurrency)
        unreachable = asyncio.Event()

        async def describe(image: ExtractedElement) -> ExtractedElement:
            async with slots:
                # Once the model is unreachable, the job stops calling it.
                if unreachable.is_set():
                    return image.with_description(
                        status=DescriptionStatus.NOT_DESCRIBED
                    )
                return await self._describe_one(
                    describer, image, by_id, links, unreachable
                )

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(describe(by_id[i])) for i in chosen]
        for task in tasks:
            by_id[task.result().id] = task.result()
        return [by_id[element.id] for element in elements]

    async def _describe_one(
        self,
        describer: FigureDescriber,
        image: ExtractedElement,
        by_id: dict[uuid.UUID, ExtractedElement],
        links: Sequence[ElementRelationship],
        unreachable: asyncio.Event,
    ) -> ExtractedElement:
        context = description_context(image, elements=by_id, relationships=links)
        # Only figures whose crop was stored are described, under this derived key.
        key = ExtractedElement.image_key_for(
            document_id=image.document_id, element_id=image.id
        )
        png = await self._blobs.read_bytes(key)
        try:
            text = await describer.describe(
                image_png=png, caption=context.caption, context=context.context
            )
        except _UNREACHABLE:
            unreachable.set()
            logger.warning("vision model unreachable, remaining figures skipped")
            return image.with_description(status=DescriptionStatus.NOT_DESCRIBED)
        except ProviderResponseError:
            logger.warning("vision model rejected figure %s", image.id)
            return image.with_description(status=DescriptionStatus.NOT_DESCRIBED)
        return image.with_description(
            status=DescriptionStatus.DESCRIBED,
            description=text,
            unverified_identifiers=unverified_identifiers(
                text, labels=image.labels, caption=context.caption
            ),
        )

    async def _index_units(
        self,
        document: Document,
        elements: Sequence[ExtractedElement],
        links: Sequence[ElementRelationship],
        stage: _Stage,
    ) -> tuple[RetrievalUnit, ...]:
        await stage(JobStage.BUILDING_UNITS)
        units = build_units(
            document_id=document.id,
            document_sha256=document.sha256,
            elements=elements,
            relationships=links,
            counter=self._tokens,
            max_tokens=self._options.max_unit_tokens,
        )
        await stage(JobStage.EMBEDDING)
        limit = self._options.embedder_max_input_tokens
        inputs = [self._tokens.truncate(unit.embedding_text, limit) for unit in units]
        vectors = await _using(EMBEDDING_MODEL, self._embedder.embed(inputs))
        await stage(JobStage.INDEXING)
        await _using(VECTOR_INDEX, self._index.upsert_units(units, vectors))
        return units

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
        self,
        job: IngestionJob,
        lease_token: uuid.UUID,
        code: FailureCode,
        reason: str,
    ) -> IngestionJob:
        try:
            await self._index.delete_document(job.document_id)
        except ProviderError:
            # The points stay hidden, and the next ingestion deletes them first.
            logger.warning("points of a failed job could not be deleted")
        return await self._jobs.fail(
            job_id=job.id, lease_token=lease_token, code=code, reason=reason
        )


async def _using[T](service: str, call: Awaitable[T]) -> T:
    """Await a call to an external service, naming it when it fails."""
    try:
        return await call
    except ProviderError as error:
        transient = isinstance(error, _UNREACHABLE)
        raise ServiceFailedError(service, transient=transient) from error


def _summary(
    extraction: _Extraction,
    elements: Sequence[ExtractedElement],
    links: Sequence[ElementRelationship],
    units: Sequence[RetrievalUnit],
) -> JobSummary:
    statuses = [e.description_status for e in elements if e.kind is ElementKind.IMAGE]
    continued = {link.target_id for link in links if link.kind is _CONTINUES}
    continuing = {link.source_id for link in links if link.kind is _CONTINUES}
    return JobSummary(
        pages=extraction.pages,
        text_elements=sum(e.kind in _TEXT_KINDS for e in elements),
        tables=sum(e.kind is ElementKind.TABLE for e in elements),
        table_chains=len(continued - continuing),
        images=len(statuses),
        figures_described=statuses.count(DescriptionStatus.DESCRIBED),
        figures_skipped=statuses.count(DescriptionStatus.SKIPPED),
        figures_not_described=statuses.count(DescriptionStatus.NOT_DESCRIBED),
        retrieval_units=len(units),
        recognized_pages=len(extraction.recognized),
    )


def _has_text(element: ExtractedElement) -> bool:
    return element.kind not in _NON_TEXT_KINDS and bool(
        element.text and element.text.strip()
    )
