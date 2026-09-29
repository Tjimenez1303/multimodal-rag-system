"""Ports: the interfaces through which the ingestion core reaches the outside world.

Adapters implement these protocols, and the composition root wires them into the use
cases. Every port has a production adapter and an in-memory fake used by the tests.
"""

import uuid
from collections.abc import AsyncIterable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobSummary,
    RetrievalUnit,
)


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results from a paginated query.

    Attributes:
        items: Results in this page.
        next_cursor: Opaque cursor of the next page, or ``None`` on the last page.
    """

    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PdfInfo:
    """What the upload needs to know about a PDF before accepting it.

    Attributes:
        page_count: Number of pages, or ``None`` when the file is encrypted.
        encrypted: Whether the file is password protected or encrypted.
    """

    page_count: int | None
    encrypted: bool


@dataclass(frozen=True, slots=True)
class ExtractionBatch:
    """Elements extracted from a contiguous range of pages.

    Attributes:
        first_page: First page of the batch, 1-based.
        last_page: Last page of the batch, inclusive.
        pages_total: Pages in the whole document.
        elements: Elements of the batch in reading order.
        images: PNG bytes of each image element, keyed by element id.
        recognized_pages: Pages of the batch whose text came from recognition.
    """

    first_page: int
    last_page: int
    pages_total: int
    elements: tuple[ExtractedElement, ...]
    images: dict[uuid.UUID, bytes] = field(default_factory=dict)
    recognized_pages: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A retrieval unit returned by a search, with its fused score.

    Attributes:
        unit: The matching unit.
        score: Fused relevance score, higher is better.
    """

    unit: RetrievalUnit
    score: float


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime:
        """Return the current time with a UTC time zone."""
        ...


class DocumentRepository(Protocol):
    """Persistence of documents, identified by the fingerprint of their bytes."""

    async def register(self, document: Document) -> tuple[Document, bool]:
        """Store a document unless one with the same fingerprint exists.

        Args:
            document: Document to store.

        Returns:
            The stored document and ``True`` when it was created, or the existing
            document with the same fingerprint and ``False``.
        """
        ...

    async def get(self, document_id: uuid.UUID) -> Document:
        """Return a document by id.

        Raises:
            DocumentNotFoundError: If no document has this id.
        """
        ...

    async def list_page(self, *, limit: int, cursor: str | None) -> Page[Document]:
        """Return documents newest first.

        Args:
            limit: Largest number of documents to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            One page of documents.
        """
        ...


class JobQueue(Protocol):
    """Durable queue and store of ingestion jobs with leases and fencing.

    Every write made on behalf of a running attempt carries its lease token. A write
    whose token is no longer current raises ``LeaseLostError`` and changes nothing.
    """

    async def enqueue(self, job: IngestionJob) -> None:
        """Store a new pending job and wake up an idle worker."""
        ...

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        """Return a job by id.

        Raises:
            JobNotFoundError: If no job has this id.
        """
        ...

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        """Return the most recent job of a document, if any."""
        ...

    async def claim(
        self, *, worker_id: str, lease_seconds: int, now: datetime
    ) -> IngestionJob | None:
        """Claim the oldest claimable job for this worker.

        A job is claimable when it is pending, or processing with an expired lease.
        A claim that would exceed the attempt limit fails that job instead.

        Returns:
            The claimed job in ``processing`` with a fresh lease, or ``None`` when no
            job is claimable.
        """
        ...

    async def heartbeat(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int
    ) -> None:
        """Extend the lease of a running attempt.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        ...

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

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        ...

    async def complete(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, summary: JobSummary
    ) -> IngestionJob:
        """Mark a running attempt as completed.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        ...

    async def fail(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        code: FailureCode,
        reason: str,
    ) -> IngestionJob:
        """Mark a running attempt as failed.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        ...


class ElementRepository(Protocol):
    """Persistence of extracted elements and their relationships."""

    async def replace_for_document(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        document_id: uuid.UUID,
        elements: Sequence[ExtractedElement],
        relationships: Sequence[ElementRelationship],
    ) -> None:
        """Replace every element of a document in one transaction.

        Raises:
            LeaseLostError: If the job's lease token is no longer current.
        """
        ...

    async def list_page(
        self,
        *,
        document_id: uuid.UUID,
        page_number: int | None,
        kind: ElementKind | None,
        limit: int,
        cursor: str | None,
    ) -> Page[ExtractedElement]:
        """Return the elements of a document in reading order, optionally filtered."""
        ...

    async def relationships_for(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ElementRelationship, ...]:
        """Return the relationships that start from the given elements."""
        ...

    async def get(
        self, *, document_id: uuid.UUID, element_id: uuid.UUID
    ) -> ExtractedElement:
        """Return one element of a document.

        Raises:
            ElementNotFoundError: If the document has no such element.
        """
        ...


class BlobStorage(Protocol):
    """Storage of original PDFs and figure crops under string keys."""

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        """Write a stream atomically under a key.

        Returns:
            The number of bytes written.
        """
        ...

    async def save_bytes(self, key: str, data: bytes) -> None:
        """Write a small payload atomically under a key."""
        ...

    async def read_bytes(self, key: str) -> bytes:
        """Return the content stored under a key.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        ...

    async def move(self, source: str, destination: str) -> None:
        """Rename a stored object, replacing any object at the destination.

        Raises:
            BlobNotFoundError: If nothing is stored under the source key.
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove a stored object if it exists."""
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object is stored under a key."""
        ...

    def materialize(self, key: str) -> AbstractContextManager[Path]:
        """Expose a stored object as a local file for the duration of a block.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        ...


class PdfInspector(Protocol):
    """Cheap checks on an uploaded file before a job is created."""

    def inspect(self, path: Path) -> PdfInfo:
        """Read the page count and encryption flag of a PDF.

        Raises:
            UnsupportedMediaTypeError: If the file is not a PDF by content.
        """
        ...


class DocumentExtractor(Protocol):
    """Layout-aware extraction of typed elements from a PDF."""

    def extract(
        self,
        *,
        path: Path,
        document_id: uuid.UUID,
        document_sha256: str,
        batch_size: int,
    ) -> Iterator[ExtractionBatch]:
        """Extract elements page batch by page batch.

        Blocking: the caller runs it in a worker thread.

        Raises:
            EncryptedDocumentError: If the PDF is encrypted.
            CorruptDocumentError: If the PDF cannot be parsed.
        """
        ...


class FigureDescriber(Protocol):
    """Vision model that describes a figure for search indexing."""

    async def describe(
        self, *, image_png: bytes, caption: str | None, context: str | None
    ) -> str:
        """Return a short description of a figure plus its printed labels.

        Args:
            image_png: The figure as PNG bytes.
            caption: Caption of the figure, if any.
            context: Text surrounding the figure, if any.

        Returns:
            The description, written in the language of the caption and context, or
            in English when both are missing.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request.
        """
        ...


class Embedder(Protocol):
    """Model that turns passages into dense vectors."""

    @property
    def dimensions(self) -> int:
        """Length of every returned vector."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per passage, in the same order.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request.
            DataInconsistencyError: If a vector has an unexpected length.
        """
        ...


class TokenCounter(Protocol):
    """Tokenizer of the embedding model, used to size retrieval units."""

    def count(self, text: str) -> int:
        """Return the number of tokens in a text."""
        ...


class VectorIndex(Protocol):
    """Hybrid index of retrieval units with dense and keyword vectors."""

    async def ensure_collection(self) -> None:
        """Create the collection and its payload indexes when missing."""
        ...

    async def upsert_units(
        self, units: Sequence[RetrievalUnit], vectors: Sequence[Sequence[float]]
    ) -> None:
        """Write units with their dense vectors, hidden from search."""
        ...

    async def publish(self, document_id: uuid.UUID) -> None:
        """Make every unit of a document visible to search."""
        ...

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Remove every unit of a document."""
        ...

    async def search_hybrid(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        """Return visible units ranked by fused dense and keyword relevance."""
        ...
