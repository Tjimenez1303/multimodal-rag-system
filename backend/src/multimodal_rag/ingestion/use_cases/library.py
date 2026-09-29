"""Reading what ingestion captured, served by the REST API."""

import uuid
from dataclasses import dataclass

from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    IngestionJob,
    JobStatus,
)
from multimodal_rag.ingestion.errors import (
    BlobNotFoundError,
    ImageNotFoundError,
    IngestionNotCompletedError,
    PageNotFoundError,
)
from multimodal_rag.ingestion.ports import (
    BlobStorage,
    DocumentRepository,
    ElementRepository,
    JobQueue,
    Page,
)
from multimodal_rag.shared.errors import DataInconsistencyError


@dataclass(frozen=True, slots=True)
class DocumentView:
    """A document together with its newest job.

    Attributes:
        document: The document.
        latest_job: Its newest job, or ``None`` while the upload that registered it
            has not enqueued the job, or after that enqueue failed.
    """

    document: Document
    latest_job: IngestionJob | None


class ListDocuments:
    """Lists the documents the system knows about, newest first.

    Args:
        documents: Document persistence.
        jobs: Job store, to find each document's latest job.
    """

    def __init__(self, *, documents: DocumentRepository, jobs: JobQueue) -> None:
        self._documents = documents
        self._jobs = jobs

    async def __call__(
        self, *, limit: int, cursor: str | None = None
    ) -> Page[DocumentView]:
        """Return one page of documents with their latest jobs.

        Args:
            limit: Largest number of documents to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            The documents, newest first, and the cursor of the next page.

        Raises:
            InvalidCursorError: If the cursor was not issued by the API.
        """
        page = await self._documents.list_page(limit=limit, cursor=cursor)
        latest = await self._jobs.latest_for_documents(
            [document.id for document in page.items]
        )
        views = tuple(
            DocumentView(document=document, latest_job=latest.get(document.id))
            for document in page.items
        )
        return Page(items=views, next_cursor=page.next_cursor)


class GetDocument:
    """Returns one document with its latest job.

    Args:
        documents: Document persistence.
        jobs: Job store, to find the document's latest job.
    """

    def __init__(self, *, documents: DocumentRepository, jobs: JobQueue) -> None:
        self._documents = documents
        self._jobs = jobs

    async def __call__(self, document_id: uuid.UUID) -> DocumentView:
        """Return a document and its latest job.

        Args:
            document_id: Id of the document.

        Returns:
            The document with its newest job.

        Raises:
            DocumentNotFoundError: If no document has this id.
        """
        document = await self._documents.get(document_id)
        job = await self._jobs.latest_for_document(document_id)
        return DocumentView(document=document, latest_job=job)


@dataclass(frozen=True, slots=True)
class ElementView:
    """An element together with every relationship that touches it.

    Attributes:
        element: The extracted element.
        relationships: Links whose source or target is the element.
    """

    element: ExtractedElement
    relationships: tuple[ElementRelationship, ...]


class ListDocumentElements:
    """Lists the captured elements of a document whose ingestion completed.

    Args:
        documents: Document persistence.
        jobs: Job store, to find the document's latest job.
        elements: Element persistence.
    """

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobQueue,
        elements: ElementRepository,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._elements = elements

    async def __call__(
        self,
        document_id: uuid.UUID,
        *,
        page_number: int | None = None,
        kind: ElementKind | None = None,
        limit: int,
        cursor: str | None = None,
    ) -> Page[ElementView]:
        """Return one page of elements in reading order.

        Args:
            document_id: Document whose elements are listed.
            page_number: Only elements of this 1-based page, when set.
            kind: Only elements of this kind, when set.
            limit: Largest number of elements to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            The elements with their relationships and the cursor of the next page.

        Raises:
            DocumentNotFoundError: If no document has this id.
            IngestionNotCompletedError: If the document's latest job has not
                completed.
            InvalidCursorError: If the cursor was not issued by the API.
        """
        await self._documents.get(document_id)
        job = await self._jobs.latest_for_document(document_id)
        if job is None or job.status is not JobStatus.COMPLETED:
            raise IngestionNotCompletedError(
                f"Document {document_id} has no completed ingestion"
            )
        page = await self._elements.list_page(
            document_id=document_id,
            page_number=page_number,
            kind=kind,
            limit=limit,
            cursor=cursor,
        )
        ids = [element.id for element in page.items]
        links = await self._elements.relationships_for(ids) if ids else ()
        views = tuple(
            ElementView(
                element=element,
                relationships=tuple(
                    link
                    for link in links
                    if element.id in (link.source_id, link.target_id)
                ),
            )
            for element in page.items
        )
        return Page(items=views, next_cursor=page.next_cursor)


class GetElementImage:
    """Returns the stored crop of an image element.

    Args:
        elements: Element persistence.
        blobs: Storage of the figure crops.
    """

    def __init__(self, *, elements: ElementRepository, blobs: BlobStorage) -> None:
        self._elements = elements
        self._blobs = blobs

    async def __call__(self, document_id: uuid.UUID, element_id: uuid.UUID) -> bytes:
        """Return the PNG crop of an image.

        Args:
            document_id: Document the element belongs to.
            element_id: Id of the image element.

        Returns:
            The PNG bytes.

        Raises:
            ElementNotFoundError: If the document has no such element.
            ImageNotFoundError: If the element has no stored image.
            DataInconsistencyError: If the stored crop of an image is missing.
        """
        element = await self._elements.get(
            document_id=document_id, element_id=element_id
        )
        if element.image_key is None:
            raise ImageNotFoundError(f"Element {element_id} has no image")
        try:
            return await self._blobs.read_bytes(element.image_key)
        except BlobNotFoundError as error:
            raise DataInconsistencyError(
                f"The crop of image {element_id} is missing"
            ) from error


class GetPageImage:
    """Returns the rendered image of a page of a completed document.

    Pages are rendered and stored by the worker during extraction, so no PDF is
    processed here.

    Args:
        documents: Document persistence.
        jobs: Job store, to find the document's latest job.
        blobs: Storage of the page images.
    """

    def __init__(
        self, *, documents: DocumentRepository, jobs: JobQueue, blobs: BlobStorage
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._blobs = blobs

    async def __call__(self, document_id: uuid.UUID, page_number: int) -> bytes:
        """Return the PNG image of a page.

        Args:
            document_id: Document the page belongs to.
            page_number: 1-based page number.

        Returns:
            The PNG bytes.

        Raises:
            DocumentNotFoundError: If no document has this id.
            IngestionNotCompletedError: If the document's latest job has not
                completed.
            PageNotFoundError: If the page is outside 1 to the document's page count.
            DataInconsistencyError: If the stored image of the page is missing.
        """
        document = await self._documents.get(document_id)
        job = await self._jobs.latest_for_document(document_id)
        if job is None or job.status is not JobStatus.COMPLETED:
            raise IngestionNotCompletedError(
                f"Document {document_id} has no completed ingestion"
            )
        # A completed job learned the page count even when the upload could not.
        page_count = document.page_count or (job.summary.pages if job.summary else 0)
        if not 1 <= page_number <= page_count:
            raise PageNotFoundError(
                f"Page {page_number} is outside the document's {page_count} pages"
            )
        key = ExtractedElement.page_image_key_for(
            document_id=document_id, page_number=page_number
        )
        try:
            return await self._blobs.read_bytes(key)
        except BlobNotFoundError as error:
            raise DataInconsistencyError(
                f"The image of page {page_number} of document {document_id} is missing"
            ) from error
