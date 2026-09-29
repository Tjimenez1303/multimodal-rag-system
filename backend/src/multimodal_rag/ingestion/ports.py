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
    PageSize,
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
        page_sizes: Size of each page of the batch.
        relationships: Caption links the extractor found between the elements of
            the batch.
    """

    first_page: int
    last_page: int
    pages_total: int
    elements: tuple[ExtractedElement, ...]
    images: dict[uuid.UUID, bytes] = field(default_factory=dict)
    recognized_pages: tuple[int, ...] = ()
    page_sizes: dict[int, PageSize] = field(default_factory=dict)
    relationships: tuple[ElementRelationship, ...] = ()


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

        Args:
            document_id: Id of the document.

        Returns:
            The stored document.

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

    async def enqueue(self, job: IngestionJob) -> tuple[IngestionJob, bool]:
        """Store a new pending job and wake up an idle worker.

        A document has at most one job that has not failed. When a concurrent upload
        already enqueued one for the same document, that job is kept.

        Args:
            job: Pending job to store.

        Returns:
            The stored job and ``True``, or the document's existing job that has not
            failed and ``False``.
        """
        ...

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        """Return a job by id.

        Args:
            job_id: Id of the job.

        Returns:
            The stored job.

        Raises:
            JobNotFoundError: If no job has this id.
        """
        ...

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        """Return the most recent job of a document, if any.

        Args:
            document_id: Document whose jobs are searched.

        Returns:
            The newest job, or ``None`` when the document has none.
        """
        ...

    async def claim(self, *, worker_id: str, lease_seconds: int) -> IngestionJob | None:
        """Claim the oldest claimable job for this worker.

        A job is claimable when it is pending, or processing with an expired lease.
        A claim that would exceed the attempt limit fails that job instead. Leases
        are measured on the queue's own clock, shared by every worker.

        Args:
            worker_id: Holder of the new lease, for diagnostics.
            lease_seconds: Duration of the new lease.

        Returns:
            The claimed job in ``processing`` with a fresh lease, or ``None`` when no
            job is claimable.
        """
        ...

    async def heartbeat(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int
    ) -> None:
        """Extend the lease of a running attempt.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            lease_seconds: New lease duration from now.

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

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            stage: Step being run.
            pages_done: Pages processed so far.
            pages_total: Pages to process, when known.

        Raises:
            LeaseLostError: If the token is no longer current.
        """
        ...

    async def complete(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, summary: JobSummary
    ) -> IngestionJob:
        """Mark a running attempt as completed.

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            summary: Counts of what the job captured.

        Returns:
            The completed job.

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

        Args:
            job_id: Job being processed.
            lease_token: Token of the attempt.
            code: Machine-readable cause.
            reason: Human-readable reason without document content.

        Returns:
            The failed job.

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

        Args:
            job_id: Job whose attempt writes the elements.
            lease_token: Token of the attempt.
            document_id: Document whose elements are replaced.
            elements: New elements of the document.
            relationships: Links between the new elements.

        Raises:
            LeaseLostError: If the job's lease token is no longer current.
            DataInconsistencyError: If the job ingests another document.
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
        """Return the elements of a document in reading order, optionally filtered.

        Args:
            document_id: Document whose elements are listed.
            page_number: Only elements of this 1-based page, when set.
            kind: Only elements of this kind, when set.
            limit: Largest number of elements to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            One page of elements.

        Raises:
            InvalidCursorError: If the cursor was not issued by the repository.
        """
        ...

    async def relationships_for(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ElementRelationship, ...]:
        """Return the relationships that touch the given elements.

        Args:
            element_ids: Elements at either end of the relationships.

        Returns:
            Every relationship whose source or target is one of the elements.
        """
        ...

    async def get(
        self, *, document_id: uuid.UUID, element_id: uuid.UUID
    ) -> ExtractedElement:
        """Return one element of a document.

        Args:
            document_id: Document the element belongs to.
            element_id: Id of the element.

        Returns:
            The stored element.

        Raises:
            ElementNotFoundError: If the document has no such element.
        """
        ...


class BlobStorage(Protocol):
    """Storage of original PDFs and figure crops under string keys."""

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        """Write a stream atomically under a key.

        Args:
            key: Destination key.
            chunks: Content to write, in order.

        Returns:
            The number of bytes written.
        """
        ...

    async def save_bytes(self, key: str, data: bytes) -> None:
        """Write a small payload atomically under a key.

        Args:
            key: Destination key.
            data: Content to write.
        """
        ...

    async def read_bytes(self, key: str) -> bytes:
        """Return the content stored under a key.

        Args:
            key: Key of the object.

        Returns:
            The stored bytes.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        ...

    async def move(self, source: str, destination: str) -> None:
        """Rename a stored object, replacing any object at the destination.

        Args:
            source: Key of the object to rename.
            destination: New key of the object.

        Raises:
            BlobNotFoundError: If nothing is stored under the source key.
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove a stored object if it exists.

        Args:
            key: Key of the object.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object is stored under a key.

        Args:
            key: Key to look up.

        Returns:
            Whether the object exists.
        """
        ...

    def materialize(self, key: str) -> AbstractContextManager[Path]:
        """Expose a stored object as a local file for the duration of a block.

        Args:
            key: Key of the object.

        Returns:
            A context manager that yields the path of the local file.

        Raises:
            BlobNotFoundError: If nothing is stored under the key.
        """
        ...


class PdfInspector(Protocol):
    """Cheap checks on an uploaded file before a job is created."""

    def inspect(self, path: Path) -> PdfInfo:
        """Read the page count and encryption flag of a PDF.

        Args:
            path: Uploaded file.

        Returns:
            The page count, or ``None`` with the encrypted flag for encrypted files.

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

        Args:
            path: PDF to extract.
            document_id: Document the elements belong to.
            document_sha256: Fingerprint used to derive stable element ids.
            batch_size: Pages converted per batch.

        Returns:
            An iterator over the batches, in page order.

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

        Args:
            texts: Passages to embed.

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
        """Return the number of tokens the embedding model reads for a text.

        Args:
            text: Text to count.

        Returns:
            The token count, special tokens included.
        """
        ...

    def truncate(self, text: str, max_tokens: int) -> str:
        """Cut a text at a token boundary so the model reads at most ``max_tokens``.

        Args:
            text: Text to shorten.
            max_tokens: Largest token count, special tokens included.

        Returns:
            The text itself when it fits, or its longest prefix that fits.
        """
        ...


class VectorIndex(Protocol):
    """Hybrid index of retrieval units with dense and keyword vectors."""

    async def ensure_collection(self) -> None:
        """Create the collection and its payload indexes when missing."""
        ...

    async def upsert_units(
        self, units: Sequence[RetrievalUnit], vectors: Sequence[Sequence[float]]
    ) -> None:
        """Write units with their dense vectors, hidden from search.

        Args:
            units: Units to write.
            vectors: Dense vector of each unit, in the same order.
        """
        ...

    async def publish(self, document_id: uuid.UUID) -> None:
        """Make every unit of a document visible to search.

        Args:
            document_id: Document whose units are published.
        """
        ...

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Remove every unit of a document.

        Args:
            document_id: Document whose units are removed.
        """
        ...

    async def search_hybrid(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        """Return visible units ranked by fused dense and keyword relevance.

        Args:
            query_text: Query for the keyword side.
            query_vector: Dense vector of the query.
            limit: Largest number of hits.
            document_ids: Only units of these documents, when set.
        """
        ...
