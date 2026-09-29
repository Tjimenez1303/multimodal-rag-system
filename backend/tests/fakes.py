"""In-memory fakes that implement every port, used instead of mocks in unit tests."""

import asyncio
import hashlib
import re
import tempfile
import uuid
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Collection,
    Generator,
    Iterator,
    Sequence,
)
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from multimodal_rag.adapters.postgres.pagination import decode_cursor, encode_cursor
from multimodal_rag.answering.domain import GeneratedAnswer, GroundedPrompt
from multimodal_rag.answering.errors import AnsweringBusyError
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
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
)

EMBEDDING_DIMENSIONS = 1024


class FrozenClock:
    """Clock that only moves when a test advances it."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def pending_job(
    clock: FrozenClock,
    *,
    document_id: uuid.UUID | None = None,
    correlation_id: str = "req-1",
    max_attempts: int = 3,
) -> IngestionJob:
    """Build a pending job created at the clock's current time."""
    return IngestionJob.create(
        job_id=uuid.uuid4(),
        document_id=document_id or uuid.uuid4(),
        max_attempts=max_attempts,
        correlation_id=correlation_id,
        now=clock.now(),
    )


async def claim_next(jobs: InMemoryJobQueue) -> IngestionJob:
    """Claim the oldest pending job, failing the test when there is none."""
    job = await jobs.claim(worker_id="worker-1", lease_seconds=90)
    assert job is not None and job.lease_token is not None
    return job


async def finish_next(
    jobs: InMemoryJobQueue, *, succeed: bool, pages: int = 12
) -> IngestionJob:
    """Claim the oldest pending job and complete it, or fail it as encrypted."""
    job = await claim_next(jobs)
    assert job.lease_token is not None
    if succeed:
        return await jobs.complete(
            job_id=job.id, lease_token=job.lease_token, summary=JobSummary(pages=pages)
        )
    return await jobs.fail(
        job_id=job.id,
        lease_token=job.lease_token,
        code=FailureCode.ENCRYPTED_DOCUMENT,
        reason="The PDF is password protected or encrypted.",
    )


def _offset(parts: list[str]) -> int:
    [position] = parts
    return int(position)


def _page_of[T](items: list[T], *, limit: int, cursor: str | None) -> Page[T]:
    # Opaque cursors like the Postgres adapters, so invalid ones fail the same way.
    start = 0 if cursor is None else decode_cursor(cursor, _offset)
    chunk = items[start : start + limit]
    has_more = start + limit < len(items)
    return Page(
        items=tuple(chunk),
        next_cursor=encode_cursor(str(start + limit)) if has_more else None,
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

    async def get_many(self, document_ids: Sequence[uuid.UUID]) -> tuple[Document, ...]:
        return tuple(
            self.documents[document_id]
            for document_id in dict.fromkeys(document_ids)
            if document_id in self.documents
        )


class InMemoryJobQueue:
    """Job queue with the same lease, attempt and fencing rules as the real one."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.jobs: dict[uuid.UUID, IngestionJob] = {}
        self.notifications = 0

    async def enqueue(self, job: IngestionJob) -> tuple[IngestionJob, bool]:
        for existing in self.jobs.values():
            if (
                existing.document_id == job.document_id
                and existing.status is not JobStatus.FAILED
            ):
                return existing, False
        self.jobs[job.id] = job
        self.notifications += 1
        return job, True

    async def get(self, job_id: uuid.UUID) -> IngestionJob:
        try:
            return self.jobs[job_id]
        except KeyError:
            raise JobNotFoundError(f"Job {job_id} not found") from None

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        jobs = [job for job in self.jobs.values() if job.document_id == document_id]
        return max(jobs, key=lambda job: (job.created_at, job.id), default=None)

    async def latest_for_documents(
        self, document_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, IngestionJob]:
        latest = {
            document_id: await self.latest_for_document(document_id)
            for document_id in document_ids
        }
        return {key: job for key, job in latest.items() if job is not None}

    async def claim(self, *, worker_id: str, lease_seconds: int) -> IngestionJob | None:
        now = self.clock.now()
        for job in sorted(self.jobs.values(), key=lambda j: j.created_at):
            if not self._claimable(job, now):
                continue
            if job.attempts_exhausted:
                self.jobs[job.id] = job.fail_interrupted(now=now)
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
            updated_at=self.clock.now(),
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

    def check_lease(self, job_id: uuid.UUID, lease_token: uuid.UUID) -> IngestionJob:
        return self._fenced(job_id, lease_token)

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
        job = self.queue.check_lease(job_id, lease_token)
        if job.document_id != document_id:
            raise DataInconsistencyError(f"Job {job_id} ingests another document")
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
            if wanted & {relationship.source_id, relationship.target_id}
        )

    async def get(
        self, *, document_id: uuid.UUID, element_id: uuid.UUID
    ) -> ExtractedElement:
        for element in self.elements.get(document_id, []):
            if element.id == element_id:
                return element
        raise ElementNotFoundError(f"Element {element_id} not found")

    async def get_many(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ExtractedElement, ...]:
        wanted = set(element_ids)
        return tuple(
            element
            for elements in self.elements.values()
            for element in elements
            if element.id in wanted
        )


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
    """Describes figures from their caption, or raises the configured error.

    ``replies`` overrides the text returned for a caption and ``failures`` the error
    raised for a caption, ``error`` applies to every call. Each call yields to the
    event loop once, so concurrent calls overlap and ``max_in_flight`` records how
    many ran at the same time.
    """

    error: Exception | None = None
    replies: dict[str | None, str] = field(default_factory=dict)
    failures: dict[str | None, Exception] = field(default_factory=dict)
    calls: list[tuple[bytes, str | None, str | None]] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0

    async def describe(
        self, *, image_png: bytes, caption: str | None, context: str | None
    ) -> str:
        self.calls.append((image_png, caption, context))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            failure = self.failures.get(caption, self.error)
            if failure is not None:
                raise failure
            default = f"Figure showing {caption or 'an unlabeled diagram'}"
            return self.replies.get(caption, default)
        finally:
            self.in_flight -= 1


class FakeEmbedder:
    """Deterministic vectors derived from a hash of each passage or query."""

    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self._dimensions = dimensions
        self.calls: list[list[str]] = []
        self.queries: list[str] = []
        self.error: Exception | None = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self.error is not None:
            raise self.error
        return self._vector(f"query:{text}")

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        repeated = (seed * (self._dimensions // len(seed) + 1))[: self._dimensions]
        return [byte / 255 for byte in repeated]


class WordTokenCounter:
    """Counts whitespace-separated words as tokens."""

    def count(self, text: str) -> int:
        return len(text.split())

    def truncate(self, text: str, max_tokens: int) -> str:
        words = text.split()
        return text if len(words) <= max_tokens else " ".join(words[:max_tokens])


@dataclass
class _IndexedUnit:
    unit: RetrievalUnit
    vector: list[float]
    visible: bool = False


def _words(text: str) -> set[str]:
    return set(re.findall(r"[\w-]+", text.lower()))


class InMemoryVectorIndex:
    """Index that ranks units by word overlap with the query.

    ``failures`` maps a method name to the error that method raises. Each hit
    carries the similarity set for its unit in ``similarities``, or
    ``default_similarity``. ``searches`` records the arguments of every search.
    """

    def __init__(self, *, default_similarity: float = 1.0) -> None:
        self.points: dict[uuid.UUID, _IndexedUnit] = {}
        self.collection_ready = False
        self.failures: dict[str, Exception] = {}
        self.deletions: list[uuid.UUID] = []
        self.similarities: dict[uuid.UUID, float] = {}
        self.default_similarity = default_similarity
        self.searches: list[dict[str, object]] = []

    def _fail(self, operation: str) -> None:
        if operation in self.failures:
            raise self.failures[operation]

    async def ensure_collection(self) -> None:
        self.collection_ready = True

    async def upsert_units(
        self, units: Sequence[RetrievalUnit], vectors: Sequence[Sequence[float]]
    ) -> None:
        self._fail("upsert_units")
        for unit, vector in zip(units, vectors, strict=True):
            self.points[unit.id] = _IndexedUnit(unit=unit, vector=list(vector))

    async def publish(self, document_id: uuid.UUID) -> None:
        self._fail("publish")
        for point in self.points.values():
            if point.unit.document_id == document_id:
                point.visible = True

    async def delete_document(self, document_id: uuid.UUID) -> None:
        self._fail("delete_document")
        self.deletions.append(document_id)
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
        self.searches.append(
            {"query_text": query_text, "limit": limit, "document_ids": document_ids}
        )
        self._fail("search_hybrid")
        query = _words(query_text)
        hits = [
            SearchHit(
                unit=point.unit,
                score=float(len(query & _words(point.unit.text))),
                similarity=self.similarities.get(
                    point.unit.id, self.default_similarity
                ),
            )
            for point in self.points.values()
            if point.visible
            and (document_ids is None or point.unit.document_id in document_ids)
        ]
        ranked = sorted((hit for hit in hits if hit.score > 0), key=lambda h: -h.score)
        return ranked[:limit]


@dataclass
class FakeAnswerGenerator:
    """Answers with scripted replies in order, then with ``default``.

    A reply that is an exception is raised instead. Every prompt is recorded, and
    ``delay_seconds`` makes each call sleep first, so tests can exceed deadlines or
    cancel a running generation.
    """

    replies: list[GeneratedAnswer | Exception] = field(default_factory=list)
    default: GeneratedAnswer = field(
        default_factory=lambda: GeneratedAnswer(text="Answer [1].", not_covered="")
    )
    delay_seconds: float = 0
    prompts: list[GroundedPrompt] = field(default_factory=list)
    cancelled: int = 0

    async def generate(self, prompt: GroundedPrompt) -> GeneratedAnswer:
        self.prompts.append(prompt)
        try:
            await asyncio.sleep(self.delay_seconds)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        reply = self.replies.pop(0) if self.replies else self.default
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeAnswerSlots:
    """Admits ``capacity`` questions at once and lets ``queue_limit`` more wait."""

    def __init__(self, *, capacity: int = 2, queue_limit: int = 10) -> None:
        self._places = asyncio.Semaphore(capacity)
        self.queue_limit = queue_limit
        self.waiting = 0
        self.admitted = 0
        self.rejected = 0

    @asynccontextmanager
    async def admit(self) -> AsyncGenerator[None]:
        if self._places.locked() and self.waiting >= self.queue_limit:
            self.rejected += 1
            raise AnsweringBusyError()
        self.waiting += 1
        try:
            await self._places.acquire()
        finally:
            self.waiting -= 1
        self.admitted += 1
        try:
            yield
        finally:
            self._places.release()


@dataclass
class FakeLanguageIdentifier:
    """Returns the language of the first keyword found in the text, else a fixed one.

    ``keywords`` maps a lowercase word to a language code. A language that is not
    among the candidates falls back to the first candidate.
    """

    language: str = "en"
    keywords: dict[str, str] = field(default_factory=dict)

    def identify(self, text: str, *, candidates: Sequence[str]) -> str:
        words = _words(text)
        found = [code for word, code in self.keywords.items() if word in words]
        language = found[0] if found else self.language
        return language if language in candidates else candidates[0]
