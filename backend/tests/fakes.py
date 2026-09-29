"""In-memory fakes that implement every port, used instead of mocks in unit tests."""

import hashlib
import re
import tempfile
import uuid
from collections.abc import AsyncIterable, Generator, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    JobSummary,
    RetrievalUnit,
)
from multimodal_rag.ingestion.errors import (
    BlobNotFoundError,
    DocumentNotFoundError,
    ElementNotFoundError,
    JobNotFoundError,
    LeaseLostError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.ingestion.ports import ExtractionBatch, Page, PdfInfo, SearchHit
from multimodal_rag.shared.errors import ProviderUnavailableError

EMBEDDING_DIMENSIONS = 1024


class FrozenClock:
    """Clock that only moves when a test advances it."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _page_of[T](items: list[T], *, limit: int, cursor: str | None) -> Page[T]:
    start = int(cursor) if cursor else 0
    chunk = items[start : start + limit]
    has_more = start + limit < len(items)
    return Page(
        items=tuple(chunk), next_cursor=str(start + limit) if has_more else None
    )


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[uuid.UUID, Document] = {}

    async def register(self, document: Document) -> tuple[Document, bool]:
        for existing in self.documents.values():
            if existing.sha256 == document.sha256:
                return existing, False
        self.documents[document.id] = document
        return document, True

    async def get(self, document_id: uuid.UUID) -> Document:
        try:
            return self.documents[document_id]
        except KeyError:
            raise DocumentNotFoundError(f"Document {document_id} not found") from None

    async def list_page(self, *, limit: int, cursor: str | None) -> Page[Document]:
        newest_first = sorted(
            self.documents.values(), key=lambda d: (d.created_at, d.id), reverse=True
        )
        return _page_of(newest_first, limit=limit, cursor=cursor)


class InMemoryJobQueue:
    """Job queue with the same lease, attempt and fencing rules as the real one."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.jobs: dict[uuid.UUID, IngestionJob] = {}
        self.notifications = 0

    async def enqueue(self, job: IngestionJob) -> None:
        self.jobs[job.id] = job
        self.notifications += 1

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise JobNotFoundError(f"Job {job_id} not found") from None

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        jobs = [job for job in self.jobs.values() if job.document_id == document_id]
        return max(jobs, key=lambda job: job.created_at, default=None)

    async def claim(
        self, *, worker_id: str, lease_seconds: int, now: datetime
    ) -> IngestionJob | None:
        for job in sorted(self.jobs.values(), key=lambda j: j.created_at):
            if not self._claimable(job, now):
                continue
            if job.attempts_exhausted:
                self.jobs[job.id] = job.fail(
                    code=FailureCode.INTERRUPTED_REPEATEDLY,
                    reason=f"Processing was interrupted {job.attempt} times",
                    now=now,
                )
                continue
            claimed = job.claim(
                lease_token=uuid.uuid4(),
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                worker_id=worker_id,
                now=now,
            )
            self.jobs[job.id] = claimed
            return claimed
        return None

    async def heartbeat(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, lease_seconds: int
    ) -> None:
        job = self._fenced(job_id, lease_token)
        self.jobs[job_id] = replace(
            job,
            lease_expires_at=self.clock.now() + timedelta(seconds=lease_seconds),
        )

    async def update_progress(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        stage: JobStage,
        pages_done: int,
        pages_total: int | None,
    ) -> None:
        job = self._fenced(job_id, lease_token)
        self.jobs[job_id] = job.advance(
            stage=stage,
            pages_done=pages_done,
            pages_total=pages_total,
            now=self.clock.now(),
        )

    async def complete(
        self, *, job_id: uuid.UUID, lease_token: uuid.UUID, summary: JobSummary
    ) -> IngestionJob:
        job = self._fenced(job_id, lease_token)
        self.jobs[job_id] = job.complete(summary=summary, now=self.clock.now())
        return self.jobs[job_id]

    async def fail(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        code: FailureCode,
        reason: str,
    ) -> IngestionJob:
        job = self._fenced(job_id, lease_token)
        self.jobs[job_id] = job.fail(code=code, reason=reason, now=self.clock.now())
        return self.jobs[job_id]

    def check_lease(self, job_id: uuid.UUID, lease_token: uuid.UUID) -> None:
        self._fenced(job_id, lease_token)

    @staticmethod
    def _claimable(job: IngestionJob, now: datetime) -> bool:
        if job.status is JobStatus.PENDING:
            return True
        return (
            job.status is JobStatus.PROCESSING
            and job.lease_expires_at is not None
            and job.lease_expires_at < now
        )

    def _fenced(self, job_id: uuid.UUID, lease_token: uuid.UUID) -> IngestionJob:
        job = self.jobs.get(job_id)
        if job is None or job.lease_token != lease_token:
            raise LeaseLostError(f"Lease of job {job_id} is no longer held")
        return job


class InMemoryElementRepository:
    def __init__(self, queue: InMemoryJobQueue) -> None:
        self.queue = queue
        self.elements: dict[uuid.UUID, list[ExtractedElement]] = {}
        self.relationships: dict[uuid.UUID, list[ElementRelationship]] = {}

    async def replace_for_document(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        document_id: uuid.UUID,
        elements: Sequence[ExtractedElement],
        relationships: Sequence[ElementRelationship],
    ) -> None:
        self.queue.check_lease(job_id, lease_token)
        self.elements[document_id] = sorted(elements, key=lambda e: e.reading_order)
        self.relationships[document_id] = list(relationships)

    async def list_page(
        self,
        *,
        document_id: uuid.UUID,
        page_number: int | None,
        kind: ElementKind | None,
        limit: int,
        cursor: str | None,
    ) -> Page[ExtractedElement]:
        matching = [
            element
            for element in self.elements.get(document_id, [])
            if (page_number is None or element.page == page_number)
            and (kind is None or element.kind is kind)
        ]
        return _page_of(matching, limit=limit, cursor=cursor)

    async def relationships_for(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ElementRelationship, ...]:
        wanted = set(element_ids)
        return tuple(
            relationship
            for relationships in self.relationships.values()
            for relationship in relationships
            if relationship.source_id in wanted
        )

    async def get(
        self, *, document_id: uuid.UUID, element_id: uuid.UUID
    ) -> ExtractedElement:
        for element in self.elements.get(document_id, []):
            if element.id == element_id:
                return element
        raise ElementNotFoundError(f"Element {element_id} not found")


class InMemoryBlobStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def save_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        data = b"".join([chunk async for chunk in chunks])
        self.blobs[key] = data
        return len(data)

    async def save_bytes(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    async def read_bytes(self, key: str) -> bytes:
        try:
            return self.blobs[key]
        except KeyError:
            raise BlobNotFoundError(f"No blob stored under {key}") from None

    async def move(self, source: str, destination: str) -> None:
        self.blobs[destination] = await self.read_bytes(source)
        del self.blobs[source]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    @contextmanager
    def materialize(self, key: str) -> Generator[Path]:
        if key not in self.blobs:
            raise BlobNotFoundError(f"No blob stored under {key}")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / Path(key).name
            path.write_bytes(self.blobs[key])
            yield path


class FakePdfInspector:
    """Reports a fixed page count, or rejects files that do not start like a PDF."""

    def __init__(self, *, page_count: int = 10, encrypted: bool = False) -> None:
        self.page_count = page_count
        self.encrypted = encrypted

    def inspect(self, path: Path) -> PdfInfo:
        if not path.read_bytes().startswith(b"%PDF-"):
            raise UnsupportedMediaTypeError("File is not a PDF")
        return PdfInfo(
            page_count=None if self.encrypted else self.page_count,
            encrypted=self.encrypted,
        )


@dataclass
class FakeExtractor:
    """Returns canned batches, or raises the configured error."""

    batches: list[ExtractionBatch] = field(default_factory=list)
    error: Exception | None = None
    calls: int = 0

    def extract(
        self,
        *,
        path: Path,
        document_id: uuid.UUID,
        document_sha256: str,
        batch_size: int,
    ) -> Iterator[ExtractionBatch]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        yield from self.batches


@dataclass
class FakeFigureDescriber:
    """Describes figures from their caption, or fails when told to."""

    fail: bool = False
    calls: list[tuple[str | None, str | None]] = field(default_factory=list)

    async def describe(
        self, *, image_png: bytes, caption: str | None, context: str | None
    ) -> str:
        self.calls.append((caption, context))
        if self.fail:
            raise ProviderUnavailableError("Vision model unreachable")
        return f"Figure showing {caption or 'an unlabeled diagram'}"


class FakeEmbedder:
    """Deterministic vectors derived from a hash of each passage."""

    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions
        self.calls: list[list[str]] = []

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        repeated = (seed * (self._dimensions // len(seed) + 1))[: self._dimensions]
        return [byte / 255 for byte in repeated]


class WordTokenCounter:
    """Counts whitespace-separated words as tokens."""

    def count(self, text: str) -> int:
        return len(text.split())


@dataclass
class _IndexedUnit:
    unit: RetrievalUnit
    vector: list[float]
    visible: bool = False


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.lower()))


class InMemoryVectorIndex:
    """Index that ranks units by word overlap with the query."""

    def __init__(self) -> None:
        self.points: dict[uuid.UUID, _IndexedUnit] = {}
        self.collection_ready = False

    async def ensure_collection(self) -> None:
        self.collection_ready = True

    async def upsert_units(
        self, units: Sequence[RetrievalUnit], vectors: Sequence[Sequence[float]]
    ) -> None:
        for unit, vector in zip(units, vectors, strict=True):
            self.points[unit.id] = _IndexedUnit(unit=unit, vector=list(vector))

    async def publish(self, document_id: uuid.UUID) -> None:
        for point in self.points.values():
            if point.unit.document_id == document_id:
                point.visible = True

    async def delete_document(self, document_id: uuid.UUID) -> None:
        self.points = {
            unit_id: point
            for unit_id, point in self.points.items()
            if point.unit.document_id != document_id
        }

    async def search_hybrid(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        query = _words(query_text)
        hits = [
            SearchHit(
                unit=point.unit, score=float(len(query & _words(point.unit.text)))
            )
            for point in self.points.values()
            if point.visible
            and (document_ids is None or point.unit.document_id in document_ids)
        ]
        ranked = sorted((hit for hit in hits if hit.score > 0), key=lambda h: -h.score)
        return ranked[:limit]
