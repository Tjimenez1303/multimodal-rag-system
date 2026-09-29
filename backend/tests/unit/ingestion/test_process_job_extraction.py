import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from multimodal_rag.ingestion.domain import (
    BoundingBox,
    Document,
    ElementKind,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    JobSummary,
    TextOrigin,
    element_id_for,
)
from multimodal_rag.ingestion.errors import (
    CorruptDocumentError,
    EncryptedDocumentError,
    LeaseLostError,
)
from multimodal_rag.ingestion.figures import FigurePolicy
from multimodal_rag.ingestion.ports import ExtractionBatch
from multimodal_rag.ingestion.use_cases.processing import (
    EnrichmentOptions,
    ProcessJob,
)
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
    ExtractionError,
    StorageTimeoutError,
    StorageUnavailableError,
)
from tests.builders import LETTER
from tests.fakes import (
    FakeEmbedder,
    FakeExtractor,
    FakeFigureDescriber,
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryElementRepository,
    InMemoryJobQueue,
    InMemoryVectorIndex,
    WordTokenCounter,
    claim_next,
    pending_job,
)

SHA = "c" * 64
PNG = b"\x89PNG\r\n\x1a\n-figure"
ENRICHMENT = EnrichmentOptions(
    figure_policy=FigurePolicy(decorative_min_pages=3, decorative_min_page_share=0.2),
    figure_concurrency=2,
    near_text_max_points=72,
    max_unit_tokens=480,
    embedder_max_input_tokens=2048,
)


class RecordingJobQueue(InMemoryJobQueue):
    """Keeps every progress update, not only the latest one."""

    def __init__(self, clock: FrozenClock) -> None:
        super().__init__(clock)
        self.progress: list[tuple[JobStage, int, int | None]] = []

    async def update_progress(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        stage: JobStage,
        pages_done: int,
        pages_total: int | None,
    ) -> None:
        await super().update_progress(
            job_id=job_id,
            lease_token=lease_token,
            stage=stage,
            pages_done=pages_done,
            pages_total=pages_total,
        )
        self.progress.append((stage, pages_done, pages_total))


@dataclass
class Harness:
    clock: FrozenClock = field(default_factory=FrozenClock)
    documents: InMemoryDocumentRepository = field(
        default_factory=InMemoryDocumentRepository
    )
    blobs: InMemoryBlobStorage = field(default_factory=InMemoryBlobStorage)
    extractor: FakeExtractor = field(default_factory=FakeExtractor)

    def __post_init__(self) -> None:
        self.jobs = RecordingJobQueue(self.clock)
        self.elements = InMemoryElementRepository(self.jobs)
        self.index = InMemoryVectorIndex()
        self.process = ProcessJob(
            documents=self.documents,
            jobs=self.jobs,
            elements=self.elements,
            blobs=self.blobs,
            extractor=self.extractor,
            describer=FakeFigureDescriber(),
            embedder=FakeEmbedder(),
            token_counter=WordTokenCounter(),
            index=self.index,
            page_batch=4,
            enrichment=ENRICHMENT,
        )

    async def claimed_job(self, *, page_count: int | None = 6) -> IngestionJob:
        document = Document(
            id=uuid.uuid4(),
            sha256=SHA,
            file_name="manual.pdf",
            size_bytes=100,
            page_count=page_count,
            blob_key=Document.blob_key_for(SHA),
            created_at=self.clock.now(),
        )
        await self.documents.register(document)
        await self.blobs.save_bytes(document.blob_key, b"%PDF-1.7 content")
        await self.jobs.enqueue(pending_job(self.clock, document_id=document.id))
        return await claim_next(self.jobs)

    def stored_elements(self, job: IngestionJob) -> list[ExtractedElement]:
        return self.elements.elements.get(job.document_id, [])


def element(document_id: uuid.UUID, order: int, **values: Any) -> ExtractedElement:
    fields: dict[str, Any] = {
        "id": element_id_for(document_sha256=SHA, element_key=f"e{order}"),
        "document_id": document_id,
        "kind": ElementKind.PARAGRAPH,
        "page": 1,
        "bbox": BoundingBox(left=10, top=20, right=200, bottom=60),
        "reading_order": order,
        "text": f"paragraph {order}",
    }
    return ExtractedElement(**(fields | values))


def two_batches(document_id: uuid.UUID) -> list[ExtractionBatch]:
    figure = element(
        document_id,
        3,
        kind=ElementKind.IMAGE,
        page=3,
        text=None,
        image_class="engineering_drawing",
        labels=("V-12",),
    )
    first = ExtractionBatch(
        first_page=1,
        last_page=4,
        pages_total=6,
        elements=(
            element(document_id, 0, kind=ElementKind.HEADING, heading_level=1),
            element(document_id, 1),
            element(
                document_id,
                2,
                kind=ElementKind.TABLE,
                page=2,
                text="| a | b |",
                table=(("a", "b"),),
            ),
            figure,
        ),
        images={figure.id: PNG},
        page_sizes=dict.fromkeys(range(1, 5), LETTER),
    )
    second = ExtractionBatch(
        first_page=5,
        last_page=6,
        pages_total=6,
        elements=(
            element(
                document_id,
                4,
                page=5,
                origin=TextOrigin.RECOGNIZED,
                confidence=0.93,
            ),
            element(document_id, 5, kind=ElementKind.PAGE_FURNITURE, page=6),
        ),
        recognized_pages=(5,),
        page_sizes=dict.fromkeys(range(5, 7), LETTER),
    )
    return [first, second]


@pytest.fixture
def harness() -> Harness:
    return Harness()


async def test_progress_is_reported_after_every_page_batch(harness: Harness) -> None:
    job = await harness.claimed_job()
    harness.extractor.batches = two_batches(job.document_id)

    await harness.process(job)

    assert harness.jobs.progress == [
        (JobStage.EXTRACTING, 0, 6),
        (JobStage.EXTRACTING, 4, 6),
        (JobStage.EXTRACTING, 6, 6),
        (JobStage.DESCRIBING_FIGURES, 6, 6),
        (JobStage.BUILDING_UNITS, 6, 6),
        (JobStage.EMBEDDING, 6, 6),
        (JobStage.INDEXING, 6, 6),
        (JobStage.FINALIZING, 6, 6),
    ]


async def test_elements_are_stored_with_page_and_box_and_the_job_completes(
    harness: Harness,
) -> None:
    job = await harness.claimed_job()
    batches = two_batches(job.document_id)
    harness.extractor.batches = batches

    finished = await harness.process(job)

    stored = harness.stored_elements(job)
    assert [e.reading_order for e in stored] == [0, 1, 2, 3, 4, 5]
    assert all(e.page >= 1 and e.bbox.area > 0 for e in stored)
    figure = next(e for e in stored if e.kind is ElementKind.IMAGE)
    assert figure.image_key == f"figures/{job.document_id}/{figure.id}.png"
    assert await harness.blobs.read_bytes(figure.image_key) == PNG
    assert finished.status is JobStatus.COMPLETED
    assert finished.summary == JobSummary(
        pages=6,
        text_elements=3,
        tables=1,
        images=1,
        # The figure covers 1.6% of its page, below the 5% described figures need.
        figures_skipped=1,
        retrieval_units=4,
        recognized_pages=1,
    )
    assert (await harness.jobs.get(job.id)).status is JobStatus.COMPLETED


async def test_unknown_page_count_is_learned_from_the_extractor(
    harness: Harness,
) -> None:
    job = await harness.claimed_job(page_count=None)
    harness.extractor.batches = two_batches(job.document_id)

    await harness.process(job)

    assert harness.jobs.progress[0] == (JobStage.EXTRACTING, 0, None)
    assert harness.jobs.progress[-1] == (JobStage.FINALIZING, 6, 6)


@pytest.mark.parametrize(
    ("error", "code", "reason"),
    [
        (
            EncryptedDocumentError("password required for /data/x.pdf"),
            FailureCode.ENCRYPTED_DOCUMENT,
            "The PDF is password protected or encrypted.",
        ),
        (
            CorruptDocumentError("xref table broken at byte 99"),
            FailureCode.CORRUPT_DOCUMENT,
            "The PDF is damaged and cannot be read.",
        ),
    ],
)
async def test_unreadable_documents_fail_once_without_retry(
    harness: Harness, error: Exception, code: FailureCode, reason: str
) -> None:
    job = await harness.claimed_job()
    harness.extractor.error = error

    finished = await harness.process(job)

    assert finished.status is JobStatus.FAILED
    assert finished.failure_code is code
    assert finished.failure_reason == reason
    assert harness.extractor.calls == 1
    assert harness.stored_elements(job) == []
    assert await harness.jobs.claim(worker_id="w2", lease_seconds=90) is None


async def test_document_without_any_text_fails_with_no_extractable_text(
    harness: Harness,
) -> None:
    job = await harness.claimed_job()
    only_image = element(
        job.document_id,
        0,
        kind=ElementKind.IMAGE,
        text=None,
    )
    harness.extractor.batches = [
        ExtractionBatch(
            first_page=1, last_page=6, pages_total=6, elements=(only_image,)
        )
    ]

    finished = await harness.process(job)

    assert finished.failure_code is FailureCode.NO_EXTRACTABLE_TEXT
    assert finished.failure_reason == (
        "No text could be read or recognized on any page."
    )
    assert harness.stored_elements(job) == []


class UnmappedExtractionError(ExtractionError):
    """An extraction failure with no failure code of its own."""

    code = "unmapped_extraction_error"


@pytest.mark.parametrize(
    "error",
    [
        DataInconsistencyError("element 7 has no box"),
        RuntimeError("secret detail"),
        UnmappedExtractionError("new cause"),
    ],
)
async def test_internal_errors_fail_the_job_without_leaking_details(
    harness: Harness, error: Exception
) -> None:
    job = await harness.claimed_job()
    harness.extractor.error = error

    finished = await harness.process(job)

    assert finished.failure_code is FailureCode.INTERNAL_ERROR
    assert finished.failure_reason == "Processing failed because of an internal error."


async def test_a_worker_whose_lease_was_taken_over_aborts_without_writing(
    harness: Harness,
) -> None:
    stale = await harness.claimed_job()
    harness.extractor.batches = two_batches(stale.document_id)
    harness.clock.advance(seconds=91)
    current = await harness.jobs.claim(worker_id="w2", lease_seconds=90)
    assert current is not None and current.attempt == 2

    with pytest.raises(LeaseLostError):
        await harness.process(stale)

    assert harness.stored_elements(stale) == []
    assert (await harness.jobs.get(stale.id)).status is JobStatus.PROCESSING


@pytest.mark.parametrize(
    "error", [StorageUnavailableError("db down"), StorageTimeoutError("db slow")]
)
async def test_a_database_outage_abandons_the_attempt_without_failing_the_job(
    harness: Harness, error: Exception
) -> None:
    job = await harness.claimed_job()
    harness.extractor.error = error

    with pytest.raises(type(error)):
        await harness.process(job)

    assert (await harness.jobs.get(job.id)).status is JobStatus.PROCESSING


async def test_a_job_without_a_lease_is_an_internal_inconsistency(
    harness: Harness,
) -> None:
    job = await harness.claimed_job()
    unleased = replace(job, lease_token=None)

    with pytest.raises(DataInconsistencyError):
        await harness.process(unleased)


def stored_pages(harness: Harness, document_id: uuid.UUID) -> dict[str, bytes]:
    prefix = f"pages/{document_id}/"
    return {k: v for k, v in harness.blobs.blobs.items() if k.startswith(prefix)}


async def test_every_page_image_of_every_batch_is_stored(harness: Harness) -> None:
    job = await harness.claimed_job()
    batches = two_batches(job.document_id)
    harness.extractor.batches = batches

    await harness.process(job)

    stored = stored_pages(harness, job.document_id)
    assert set(stored) == {
        ExtractedElement.page_image_key_for(document_id=job.document_id, page_number=n)
        for n in range(1, 7)
    }
    for batch in harness.extractor.yielded:
        for page_number, png in batch.page_images.items():
            key = ExtractedElement.page_image_key_for(
                document_id=job.document_id, page_number=page_number
            )
            assert stored[key] == png


async def test_a_retried_job_overwrites_the_same_page_images(harness: Harness) -> None:
    job = await harness.claimed_job()
    harness.extractor.batches = two_batches(job.document_id)
    # A database outage abandons the first attempt after its pages were stored.
    harness.index.failures["publish"] = StorageUnavailableError("db down")
    with pytest.raises(StorageUnavailableError):
        await harness.process(job)
    first = stored_pages(harness, job.document_id)
    objects = len(harness.blobs.blobs)

    del harness.index.failures["publish"]
    harness.clock.advance(seconds=91)
    retry = await claim_next(harness.jobs)
    await harness.process(retry)

    assert retry.attempt == 2

    assert stored_pages(harness, job.document_id).keys() == first.keys()
    assert len(harness.blobs.blobs) == objects
