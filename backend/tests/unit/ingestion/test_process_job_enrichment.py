import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    Document,
    ElementKind,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    RelationshipKind,
    UnitType,
)
from multimodal_rag.ingestion.figures import FigurePolicy
from multimodal_rag.ingestion.ports import ExtractionBatch
from multimodal_rag.ingestion.use_cases.processing import (
    EnrichmentOptions,
    ProcessJob,
)
from multimodal_rag.shared.errors import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StorageUnavailableError,
)
from tests.builders import LETTER, SHA, link, make
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

PNG = b"\x89PNG\r\n\x1a\n-figure"
DOCUMENT_ID = uuid.UUID("6f1d2b1e-0000-4000-8000-000000000001")
OPTIONS = EnrichmentOptions(
    figure_policy=FigurePolicy(decorative_min_pages=3, decorative_min_page_share=0.2),
    figure_concurrency=2,
    near_text_max_points=72,
    max_unit_tokens=50,
    embedder_max_input_tokens=40,
)


class RecordingJobQueue(InMemoryJobQueue):
    """Keeps the stage of every progress update."""

    def __init__(self, clock: FrozenClock) -> None:
        super().__init__(clock)
        self.stages: list[JobStage] = []

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
        self.stages.append(stage)


def drawing(order: int, *, page: int = 1, **values: Any) -> ExtractedElement:
    fields: dict[str, Any] = {
        "top": 100,
        "bottom": 300,
        "image_class": "engineering_drawing",
        "labels": ("V-12",),
    }
    return make(order, ElementKind.IMAGE, page=page, **(fields | values))


def manual() -> list[ExtractionBatch]:
    """A two-page manual with a captioned figure, a logo and a split table."""
    figure = drawing(1)
    caption = make(2, ElementKind.CAPTION, top=310, bottom=325, text="Figure 1. Pump")
    logo = drawing(3, top=740, bottom=780, image_class="logo", labels=())
    head = make(5, ElementKind.TABLE, top=500, bottom=730)
    first = ExtractionBatch(
        first_page=1,
        last_page=1,
        pages_total=2,
        elements=(
            make(0, ElementKind.HEADING, top=40, bottom=60, text="Fuel system"),
            figure,
            caption,
            logo,
            make(4, top=330, bottom=360, text="The pump feeds valve V-12."),
            head,
        ),
        images={figure.id: PNG, logo.id: b"logo-bytes"},
        page_sizes={1: LETTER},
        relationships=(link(caption, figure, RelationshipKind.CAPTION_OF),),
    )
    second = ExtractionBatch(
        first_page=2,
        last_page=2,
        pages_total=2,
        elements=(
            make(6, ElementKind.TABLE, page=2, top=60, bottom=300),
            make(7, page=2, top=320, bottom=340, text="Torque every bolt."),
        ),
        page_sizes={2: LETTER},
    )
    return [first, second]


@dataclass
class Harness:
    clock: FrozenClock = field(default_factory=FrozenClock)
    documents: InMemoryDocumentRepository = field(
        default_factory=InMemoryDocumentRepository
    )
    blobs: InMemoryBlobStorage = field(default_factory=InMemoryBlobStorage)
    extractor: FakeExtractor = field(default_factory=FakeExtractor)
    describer: FakeFigureDescriber | None = field(default_factory=FakeFigureDescriber)
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)
    index: InMemoryVectorIndex = field(default_factory=InMemoryVectorIndex)
    options: EnrichmentOptions = OPTIONS

    def __post_init__(self) -> None:
        self.jobs = RecordingJobQueue(self.clock)
        self.elements = InMemoryElementRepository(self.jobs)
        self.extractor.batches = manual()

    @property
    def process(self) -> ProcessJob:
        return ProcessJob(
            documents=self.documents,
            jobs=self.jobs,
            elements=self.elements,
            blobs=self.blobs,
            extractor=self.extractor,
            describer=self.describer,
            embedder=self.embedder,
            token_counter=WordTokenCounter(),
            index=self.index,
            page_batch=4,
            enrichment=self.options,
        )

    async def claimed_job(self) -> IngestionJob:
        document = Document(
            id=DOCUMENT_ID,
            sha256=SHA,
            file_name="manual.pdf",
            size_bytes=100,
            page_count=2,
            blob_key=Document.blob_key_for(SHA),
            created_at=self.clock.now(),
        )
        await self.documents.register(document)
        await self.blobs.save_bytes(document.blob_key, b"%PDF-1.7 content")
        await self.jobs.enqueue(pending_job(self.clock, document_id=document.id))
        return await claim_next(self.jobs)

    def stored(self) -> dict[int, ExtractedElement]:
        return {e.reading_order: e for e in self.elements.elements[DOCUMENT_ID]}


@pytest.fixture
def harness() -> Harness:
    return Harness()


async def test_the_stages_run_in_order_and_the_job_completes(harness: Harness) -> None:
    finished = await harness.process(await harness.claimed_job())

    assert finished.status is JobStatus.COMPLETED
    assert harness.jobs.stages == [
        JobStage.EXTRACTING,
        JobStage.EXTRACTING,
        JobStage.EXTRACTING,
        JobStage.DESCRIBING_FIGURES,
        JobStage.BUILDING_UNITS,
        JobStage.EMBEDDING,
        JobStage.INDEXING,
        JobStage.FINALIZING,
    ]


async def test_figures_are_described_with_their_caption_and_nearby_text(
    harness: Harness,
) -> None:
    assert harness.describer is not None
    harness.describer.replies["Figure 1. Pump"] = "Pump P-9 feeds valve V-12."

    await harness.process(await harness.claimed_job())

    [(image, caption, context)] = harness.describer.calls
    assert (image, caption, context) == (
        PNG,
        "Figure 1. Pump",
        "The pump feeds valve V-12.",
    )
    figure = harness.stored()[1]
    assert figure.description_status is DescriptionStatus.DESCRIBED
    assert figure.description == "Pump P-9 feeds valve V-12."
    assert figure.unverified_identifiers == ("P-9",)
    logo = harness.stored()[3]
    assert logo.is_decorative
    assert logo.description_status is DescriptionStatus.SKIPPED


async def test_relationships_and_the_summary_are_stored(harness: Harness) -> None:
    finished = await harness.process(await harness.claimed_job())

    kinds = {r.kind for r in harness.elements.relationships[DOCUMENT_ID]}
    assert kinds == {
        RelationshipKind.CAPTION_OF,
        RelationshipKind.NEAR,
        RelationshipKind.CONTINUES,
    }
    assert finished.summary is not None
    assert finished.summary.figures_described == 1
    assert finished.summary.figures_skipped == 1
    assert finished.summary.figures_not_described == 0
    assert finished.summary.table_chains == 1
    assert finished.summary.retrieval_units == len(harness.index.points) == 4


async def test_units_are_published_only_when_the_job_completes(
    harness: Harness,
) -> None:
    await harness.process(await harness.claimed_job())

    units = [point.unit for point in harness.index.points.values()]
    assert all(point.visible for point in harness.index.points.values())
    assert {unit.unit_type for unit in units} == {
        UnitType.TEXT,
        UnitType.FIGURE,
        UnitType.TABLE,
    }
    [table] = [unit for unit in units if unit.unit_type is UnitType.TABLE]
    assert table.pages == (1, 2)


async def test_embedding_inputs_are_contextualized_and_truncated(
    harness: Harness,
) -> None:
    harness.options = replace(OPTIONS, embedder_max_input_tokens=3)

    await harness.process(await harness.claimed_job())

    [texts] = harness.embedder.calls
    assert all(len(text.split()) <= 3 for text in texts)
    # The heading path comes first, so it survives the cut.
    assert "Fuel system The" in texts


async def test_descriptions_run_two_at_a_time(harness: Harness) -> None:
    figures = [drawing(10 + n, page=2, top=400, bottom=600) for n in range(5)]
    harness.extractor.batches = [
        *manual()[:1],
        ExtractionBatch(
            first_page=2,
            last_page=2,
            pages_total=2,
            elements=tuple(figures),
            images={figure.id: bytes([n]) + PNG for n, figure in enumerate(figures)},
            page_sizes={2: LETTER},
        ),
    ]

    await harness.process(await harness.claimed_job())

    assert harness.describer is not None
    assert harness.describer.max_in_flight == 2
    assert len(harness.describer.calls) == 6


@pytest.mark.parametrize(
    "error", [ProviderUnavailableError("down"), ProviderTimeoutError("slow")]
)
async def test_an_unreachable_vision_model_is_not_called_again(
    harness: Harness, error: Exception
) -> None:
    assert harness.describer is not None
    harness.describer.error = error
    figures = [drawing(10 + n, page=2, top=400, bottom=600) for n in range(4)]
    batches = manual()
    harness.extractor.batches = [
        batches[0],
        ExtractionBatch(
            first_page=2,
            last_page=2,
            pages_total=2,
            elements=tuple(figures),
            images={figure.id: bytes([n]) + PNG for n, figure in enumerate(figures)},
            page_sizes={2: LETTER},
        ),
    ]

    finished = await harness.process(await harness.claimed_job())

    assert finished.status is JobStatus.COMPLETED
    assert len(harness.describer.calls) <= OPTIONS.figure_concurrency
    assert finished.summary is not None
    assert finished.summary.figures_not_described == 5
    statuses = {e.description_status for e in harness.stored().values() if e.image_key}
    assert statuses == {DescriptionStatus.NOT_DESCRIBED, DescriptionStatus.SKIPPED}


async def test_a_rejected_figure_fails_alone(harness: Harness) -> None:
    assert harness.describer is not None
    harness.describer.failures["Figure 1. Pump"] = ProviderResponseError("bad")
    extra = drawing(10, page=2, top=400, bottom=600)
    batches = manual()
    harness.extractor.batches = [
        batches[0],
        ExtractionBatch(
            first_page=2,
            last_page=2,
            pages_total=2,
            elements=(*batches[1].elements, extra),
            images={extra.id: b"extra" + PNG},
            page_sizes={2: LETTER},
        ),
    ]

    finished = await harness.process(await harness.claimed_job())

    assert finished.summary is not None
    assert finished.summary.figures_not_described == 1
    assert finished.summary.figures_described == 1


async def test_disabled_descriptions_skip_every_figure() -> None:
    harness = Harness(describer=None)

    finished = await harness.process(await harness.claimed_job())

    assert finished.summary is not None
    assert finished.summary.figures_described == 0
    assert finished.summary.figures_skipped == 2
    assert harness.stored()[1].description_status is DescriptionStatus.SKIPPED


@pytest.mark.parametrize(
    ("error", "code", "reason"),
    [
        (
            ProviderUnavailableError("connection refused to 10.0.0.3"),
            FailureCode.PROVIDER_UNAVAILABLE,
            "The embedding model was unavailable after its retries.",
        ),
        (
            ProviderResponseError("input 'The pump feeds valve V-12.' too long"),
            FailureCode.INTERNAL_ERROR,
            "The embedding model rejected a request.",
        ),
    ],
)
async def test_an_embedding_failure_fails_the_job_naming_the_service(
    harness: Harness, error: Exception, code: FailureCode, reason: str
) -> None:
    harness.embedder.error = error

    finished = await harness.process(await harness.claimed_job())

    assert finished.status is JobStatus.FAILED
    assert (finished.failure_code, finished.failure_reason) == (code, reason)
    assert harness.index.points == {}


@pytest.mark.parametrize("operation", ["delete_document", "upsert_units", "publish"])
async def test_a_vector_index_failure_fails_the_job_naming_the_service(
    harness: Harness, operation: str
) -> None:
    harness.index.failures[operation] = ProviderUnavailableError("qdrant down")

    finished = await harness.process(await harness.claimed_job())

    assert finished.failure_code is FailureCode.PROVIDER_UNAVAILABLE
    assert finished.failure_reason == (
        "The vector index was unavailable after its retries."
    )


async def test_a_failed_job_leaves_nothing_searchable(harness: Harness) -> None:
    harness.index.failures["publish"] = ProviderUnavailableError("qdrant down")

    await harness.process(await harness.claimed_job())

    del harness.index.failures["publish"]
    assert harness.index.points == {}
    assert harness.index.deletions == [DOCUMENT_ID, DOCUMENT_ID]


async def test_a_new_attempt_replaces_every_point_of_the_previous_one(
    harness: Harness,
) -> None:
    obsolete = make(8, ElementKind.HEADING, page=2, top=380, bottom=395, text="Old")
    stale = make(9, page=2, top=400, bottom=420, text="Only the first attempt.")
    first, second = manual()
    harness.extractor.batches = [
        first,
        ExtractionBatch(
            first_page=2,
            last_page=2,
            pages_total=2,
            elements=(*second.elements, obsolete, stale),
            page_sizes={2: LETTER},
        ),
    ]
    # A database outage abandons the attempt after its points were written.
    harness.index.failures["publish"] = StorageUnavailableError("db down")
    job = await harness.claimed_job()
    with pytest.raises(StorageUnavailableError):
        await harness.process(job)
    written = set(harness.index.points)

    del harness.index.failures["publish"]
    harness.extractor.batches = manual()
    harness.clock.advance(seconds=91)
    retry = await claim_next(harness.jobs)
    finished = await harness.process(retry)

    assert retry.attempt == 2
    assert finished.status is JobStatus.COMPLETED
    assert set(harness.index.points) < written
    assert all(point.visible for point in harness.index.points.values())
    assert not any(
        "Only the first attempt." in point.unit.text
        for point in harness.index.points.values()
    )


async def test_reprocessing_yields_the_same_point_ids() -> None:
    ids = []
    for _ in range(2):
        harness = Harness()
        await harness.process(await harness.claimed_job())
        ids.append(set(harness.index.points))

    assert ids[0] == ids[1]
