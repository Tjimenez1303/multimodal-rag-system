import hashlib
import uuid
from dataclasses import dataclass, field

import pytest

from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    ExtractedElement,
    JobStatus,
    JobSummary,
    RelationshipKind,
)
from multimodal_rag.ingestion.errors import (
    DocumentNotFoundError,
    ElementNotFoundError,
    ImageNotFoundError,
    IngestionNotCompletedError,
    PageNotFoundError,
)
from multimodal_rag.ingestion.use_cases.library import (
    GetDocument,
    GetElementImage,
    GetPageImage,
    ListDocumentElements,
    ListDocuments,
)
from multimodal_rag.shared.errors import DataInconsistencyError
from tests.builders import DOCUMENT_ID, SHA, link, make
from tests.fakes import (
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryElementRepository,
    InMemoryJobQueue,
    claim_next,
    finish_next,
    pending_job,
)

PNG = b"\x89PNG\r\n\x1a\n-figure"


@dataclass
class Library:
    clock: FrozenClock = field(default_factory=FrozenClock)
    documents: InMemoryDocumentRepository = field(
        default_factory=InMemoryDocumentRepository
    )
    blobs: InMemoryBlobStorage = field(default_factory=InMemoryBlobStorage)

    def __post_init__(self) -> None:
        self.jobs = InMemoryJobQueue(self.clock)
        self.elements = InMemoryElementRepository(self.jobs)
        self.list_elements = ListDocumentElements(
            documents=self.documents, jobs=self.jobs, elements=self.elements
        )
        self.get_image = GetElementImage(elements=self.elements, blobs=self.blobs)
        self.list_documents = ListDocuments(documents=self.documents, jobs=self.jobs)
        self.get_document = GetDocument(documents=self.documents, jobs=self.jobs)
        self.get_page = GetPageImage(
            documents=self.documents, jobs=self.jobs, blobs=self.blobs
        )

    async def registered(self, name: str) -> Document:
        # One second apart, so creation order decides the listing order.
        self.clock.advance(seconds=1)
        sha = hashlib.sha256(name.encode()).hexdigest()
        document, _ = await self.documents.register(
            Document(
                id=uuid.uuid4(),
                sha256=sha,
                file_name=name,
                size_bytes=100,
                page_count=3,
                blob_key=Document.blob_key_for(sha),
                created_at=self.clock.now(),
            )
        )
        return document

    async def uploaded(self, name: str) -> Document:
        document = await self.registered(name)
        await self.jobs.enqueue(pending_job(self.clock, document_id=document.id))
        return document

    async def document(self) -> None:
        await self.documents.register(
            Document(
                id=DOCUMENT_ID,
                sha256=SHA,
                file_name="manual.pdf",
                size_bytes=100,
                page_count=2,
                blob_key=Document.blob_key_for(SHA),
                created_at=self.clock.now(),
            )
        )
        await self.jobs.enqueue(pending_job(self.clock, document_id=DOCUMENT_ID))

    async def ingested(self, elements: list[ExtractedElement]) -> None:
        await self.document()
        job = await claim_next(self.jobs)
        assert job.lease_token is not None
        await self.elements.replace_for_document(
            job_id=job.id,
            lease_token=job.lease_token,
            document_id=DOCUMENT_ID,
            elements=elements,
            relationships=[link(elements[1], elements[0], RelationshipKind.CAPTION_OF)],
        )
        await self.jobs.complete(
            job_id=job.id,
            lease_token=job.lease_token,
            summary=JobSummary(),
        )


@pytest.fixture
def library() -> Library:
    return Library()


def figure_and_caption() -> list[ExtractedElement]:
    image = make(0, ElementKind.IMAGE, image_key="figures/doc/figure.png")
    caption = make(1, ElementKind.CAPTION, text="Figure 1. Pump")
    return [image, caption, make(2, page=2)]


async def test_elements_come_with_every_relationship_that_touches_them(
    library: Library,
) -> None:
    elements = figure_and_caption()
    await library.ingested(elements)

    page = await library.list_elements(DOCUMENT_ID, limit=10)

    image, caption, paragraph = page.items
    edge = (elements[1].id, elements[0].id, RelationshipKind.CAPTION_OF)
    assert image.element == elements[0]
    assert [(r.source_id, r.target_id, r.kind) for r in image.relationships] == [edge]
    assert [(r.source_id, r.target_id, r.kind) for r in caption.relationships] == [edge]
    assert paragraph.relationships == ()


async def test_elements_are_filtered_by_page_and_kind_and_paginated(
    library: Library,
) -> None:
    await library.ingested(figure_and_caption())

    first = await library.list_elements(DOCUMENT_ID, page_number=1, limit=1)
    second = await library.list_elements(
        DOCUMENT_ID, page_number=1, limit=1, cursor=first.next_cursor
    )
    images = await library.list_elements(DOCUMENT_ID, kind=ElementKind.IMAGE, limit=10)

    assert [v.element.reading_order for v in (*first.items, *second.items)] == [0, 1]
    assert second.next_cursor is None
    assert [v.element.kind for v in images.items] == [ElementKind.IMAGE]


async def test_an_unknown_document_is_not_found(library: Library) -> None:
    with pytest.raises(DocumentNotFoundError):
        await library.list_elements(uuid.uuid4(), limit=10)


async def test_elements_wait_for_a_completed_ingestion(library: Library) -> None:
    await library.document()

    with pytest.raises(IngestionNotCompletedError):
        await library.list_elements(DOCUMENT_ID, limit=10)


async def test_a_failed_ingestion_has_no_elements_to_show(library: Library) -> None:
    await library.document()
    await finish_next(library.jobs, succeed=False)

    with pytest.raises(IngestionNotCompletedError):
        await library.list_elements(DOCUMENT_ID, limit=10)


async def test_the_crop_of_an_image_is_returned(library: Library) -> None:
    elements = figure_and_caption()
    await library.ingested(elements)
    await library.blobs.save_bytes("figures/doc/figure.png", PNG)

    assert await library.get_image(DOCUMENT_ID, elements[0].id) == PNG


async def test_an_element_without_an_image_has_no_crop(library: Library) -> None:
    elements = figure_and_caption()
    await library.ingested(elements)

    with pytest.raises(ImageNotFoundError):
        await library.get_image(DOCUMENT_ID, elements[1].id)


async def test_an_unknown_element_is_not_found(library: Library) -> None:
    await library.ingested(figure_and_caption())

    with pytest.raises(ElementNotFoundError):
        await library.get_image(DOCUMENT_ID, uuid.uuid4())


async def test_a_missing_crop_of_a_stored_image_is_an_inconsistency(
    library: Library,
) -> None:
    elements = figure_and_caption()
    await library.ingested(elements)

    with pytest.raises(DataInconsistencyError):
        await library.get_image(DOCUMENT_ID, elements[0].id)


async def test_documents_are_listed_newest_first_with_their_latest_job(
    library: Library,
) -> None:
    older = await library.uploaded("older.pdf")
    await finish_next(library.jobs, succeed=False)
    library.clock.advance(seconds=1)
    retry, _ = await library.jobs.enqueue(
        pending_job(library.clock, document_id=older.id)
    )
    newer = await library.uploaded("newer.pdf")

    page = await library.list_documents(limit=10)

    assert [view.document for view in page.items] == [newer, older]
    newest, oldest = page.items
    assert newest.latest_job is not None
    assert newest.latest_job.document_id == newer.id
    assert oldest.latest_job == retry
    assert page.next_cursor is None


async def test_documents_are_paginated_with_a_cursor(library: Library) -> None:
    for name in ("a.pdf", "b.pdf", "c.pdf"):
        await library.uploaded(name)

    first = await library.list_documents(limit=2)
    second = await library.list_documents(limit=2, cursor=first.next_cursor)

    listed = [view.document.file_name for view in (*first.items, *second.items)]
    assert listed == ["c.pdf", "b.pdf", "a.pdf"]
    assert second.next_cursor is None


async def test_a_document_whose_job_is_not_enqueued_has_no_latest_job(
    library: Library,
) -> None:
    document = await library.registered("manual.pdf")

    page = await library.list_documents(limit=10)
    view = await library.get_document(document.id)

    assert [item.latest_job for item in page.items] == [None]
    assert (view.document, view.latest_job) == (document, None)


async def test_a_document_is_returned_with_its_latest_job(library: Library) -> None:
    document = await library.uploaded("manual.pdf")
    completed = await finish_next(library.jobs, succeed=True)

    view = await library.get_document(document.id)

    assert view.document == document
    assert view.latest_job == completed
    assert completed.status is JobStatus.COMPLETED


async def test_getting_an_unknown_document_is_not_found(library: Library) -> None:
    with pytest.raises(DocumentNotFoundError):
        await library.get_document(uuid.uuid4())


def page_key(page_number: int) -> str:
    return ExtractedElement.page_image_key_for(
        document_id=DOCUMENT_ID, page_number=page_number
    )


async def test_the_image_of_a_page_of_a_completed_document_is_returned(
    library: Library,
) -> None:
    await library.document()
    await finish_next(library.jobs, succeed=True)
    await library.blobs.save_bytes(page_key(2), PNG)

    assert await library.get_page(DOCUMENT_ID, 2) == PNG


async def test_the_page_of_an_unknown_document_is_not_found(library: Library) -> None:
    with pytest.raises(DocumentNotFoundError):
        await library.get_page(uuid.uuid4(), 1)


async def test_a_page_waits_for_a_completed_ingestion(library: Library) -> None:
    await library.document()

    with pytest.raises(IngestionNotCompletedError):
        await library.get_page(DOCUMENT_ID, 1)
    await claim_next(library.jobs)
    with pytest.raises(IngestionNotCompletedError):
        await library.get_page(DOCUMENT_ID, 1)


async def test_a_failed_ingestion_has_no_pages(library: Library) -> None:
    await library.document()
    await finish_next(library.jobs, succeed=False)

    with pytest.raises(IngestionNotCompletedError):
        await library.get_page(DOCUMENT_ID, 1)


async def test_a_document_without_a_job_has_no_pages(library: Library) -> None:
    document = await library.registered("no-job.pdf")

    with pytest.raises(IngestionNotCompletedError):
        await library.get_page(document.id, 1)


@pytest.mark.parametrize("page_number", [0, -1, 3])
async def test_a_page_outside_the_document_is_not_found(
    library: Library, page_number: int
) -> None:
    await library.document()
    await finish_next(library.jobs, succeed=True)

    with pytest.raises(PageNotFoundError):
        await library.get_page(DOCUMENT_ID, page_number)


async def test_a_missing_page_image_of_a_completed_document_is_an_inconsistency(
    library: Library,
) -> None:
    await library.document()
    await finish_next(library.jobs, succeed=True)

    with pytest.raises(DataInconsistencyError):
        await library.get_page(DOCUMENT_ID, 1)
