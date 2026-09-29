import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from multimodal_rag.adapters.postgres.documents import PostgresDocumentRepository
from multimodal_rag.adapters.postgres.elements import PostgresElementRepository
from multimodal_rag.adapters.postgres.engine import connect, create_engine
from multimodal_rag.adapters.postgres.job_queue import PostgresJobQueue
from multimodal_rag.adapters.postgres.tables import ingestion_jobs
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    Document,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    FailureCode,
    IngestionJob,
    JobStage,
    JobStatus,
    JobSummary,
    RelationshipKind,
    TextOrigin,
)
from multimodal_rag.ingestion.errors import (
    DocumentNotFoundError,
    ElementNotFoundError,
    InvalidCursorError,
    JobNotFoundError,
    LeaseLostError,
)
from multimodal_rag.shared.config import DatabaseSettings
from multimodal_rag.shared.errors import DataInconsistencyError, StorageTimeoutError
from tests.fakes import FrozenClock, pending_job


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def documents(engine: AsyncEngine) -> PostgresDocumentRepository:
    return PostgresDocumentRepository(engine)


@pytest.fixture
def jobs(engine: AsyncEngine) -> PostgresJobQueue:
    return PostgresJobQueue(engine)


@pytest.fixture
def elements(engine: AsyncEngine) -> PostgresElementRepository:
    return PostgresElementRepository(engine)


def new_document(clock: FrozenClock, sha256: str = "d" * 64) -> Document:
    return Document(
        id=uuid.uuid4(),
        sha256=sha256,
        file_name="manual.pdf",
        size_bytes=1_024,
        page_count=71,
        blob_key=Document.blob_key_for(sha256),
        created_at=clock.now(),
    )


def new_job(clock: FrozenClock, document: Document) -> IngestionJob:
    return pending_job(clock, document_id=document.id)


async def claimed(
    jobs: PostgresJobQueue, documents: PostgresDocumentRepository, clock: FrozenClock
) -> IngestionJob:
    document, _ = await documents.register(new_document(clock))
    await jobs.enqueue(new_job(clock, document))
    job = await jobs.claim(worker_id="worker-1", lease_seconds=90)
    assert job is not None and job.lease_token is not None
    return job


class TestDocuments:
    async def test_concurrent_registrations_of_one_fingerprint_keep_one_document(
        self, documents: PostgresDocumentRepository, clock: FrozenClock
    ) -> None:
        results = await asyncio.gather(
            *(documents.register(new_document(clock)) for _ in range(10))
        )

        assert len({document.id for document, _ in results}) == 1
        assert sum(created for _, created in results) == 1

    async def test_registered_document_round_trips(
        self, documents: PostgresDocumentRepository, clock: FrozenClock
    ) -> None:
        document, created = await documents.register(new_document(clock))

        assert created is True
        assert await documents.get(document.id) == document

    async def test_unknown_document_raises_not_found(
        self, documents: PostgresDocumentRepository
    ) -> None:
        with pytest.raises(DocumentNotFoundError):
            await documents.get(uuid.uuid4())

    async def test_documents_are_listed_newest_first_across_pages(
        self, documents: PostgresDocumentRepository, clock: FrozenClock
    ) -> None:
        registered = []
        for index in range(3):
            clock.advance(seconds=1)
            document, _ = await documents.register(new_document(clock, f"{index}" * 64))
            registered.append(document.id)

        first = await documents.list_page(limit=2, cursor=None)
        second = await documents.list_page(limit=2, cursor=first.next_cursor)

        listed = [d.id for d in first.items] + [d.id for d in second.items]
        assert listed == registered[::-1]
        assert second.next_cursor is None


class TestJobQueue:
    async def test_concurrent_enqueues_for_one_document_keep_one_active_job(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        document, _ = await documents.register(new_document(clock))

        results = await asyncio.gather(
            *(jobs.enqueue(new_job(clock, document)) for _ in range(10))
        )

        assert len({job.id for job, _ in results}) == 1
        assert sum(created for _, created in results) == 1

    async def test_a_failed_job_does_not_block_a_new_one(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None
        await jobs.fail(
            job_id=job.id,
            lease_token=job.lease_token,
            code=FailureCode.CORRUPT_DOCUMENT,
            reason="The PDF is damaged and cannot be read.",
        )
        clock.advance(seconds=1)

        retry, created = await jobs.enqueue(
            IngestionJob.create(
                job_id=uuid.uuid4(),
                document_id=job.document_id,
                max_attempts=3,
                correlation_id="req-2",
                now=clock.now(),
            )
        )

        assert created is True
        assert (await jobs.latest_for_document(job.document_id)) == retry

    async def test_claim_starts_an_attempt_under_a_fresh_lease(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)

        stored = await jobs.get(job.id)
        assert stored == job
        assert stored.status is JobStatus.PROCESSING
        assert stored.attempt == 1
        assert stored.worker_id == "worker-1"
        assert stored.started_at is not None and stored.lease_expires_at is not None
        assert stored.lease_expires_at - stored.started_at == timedelta(seconds=90)

    async def test_concurrent_claimers_never_get_the_same_job(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        for index in range(5):
            document, _ = await documents.register(new_document(clock, f"{index}" * 64))
            await jobs.enqueue(new_job(clock, document))

        results = await asyncio.gather(
            *(jobs.claim(worker_id=f"w{n}", lease_seconds=90) for n in range(10))
        )

        claimed_ids = [job.id for job in results if job is not None]
        assert len(claimed_ids) == 5
        assert len(set(claimed_ids)) == 5

    async def test_claim_returns_nothing_when_no_job_is_pending(
        self, jobs: PostgresJobQueue, clock: FrozenClock
    ) -> None:
        assert await jobs.claim(worker_id="w", lease_seconds=90) is None

    async def test_progress_completion_and_summary_are_persisted(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None
        await jobs.update_progress(
            job_id=job.id,
            lease_token=job.lease_token,
            stage=JobStage.EXTRACTING,
            pages_done=8,
            pages_total=71,
        )
        progressed = await jobs.get(job.id)

        summary = JobSummary(pages=71, text_elements=400, tables=8, images=117)
        finished = await jobs.complete(
            job_id=job.id, lease_token=job.lease_token, summary=summary
        )

        assert (progressed.stage, progressed.pages_done) == (JobStage.EXTRACTING, 8)
        assert finished.status is JobStatus.COMPLETED
        assert await jobs.get(job.id) == finished
        assert finished.summary == summary

    async def test_failure_code_and_reason_are_persisted(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None

        failed = await jobs.fail(
            job_id=job.id,
            lease_token=job.lease_token,
            code=FailureCode.ENCRYPTED_DOCUMENT,
            reason="The PDF is password protected or encrypted.",
        )

        assert await jobs.get(job.id) == failed
        assert failed.failure_code is FailureCode.ENCRYPTED_DOCUMENT

    async def test_heartbeat_extends_the_lease(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None and job.lease_expires_at is not None

        await jobs.heartbeat(
            job_id=job.id, lease_token=job.lease_token, lease_seconds=900
        )

        stored = await jobs.get(job.id)
        assert stored.lease_expires_at is not None
        assert stored.lease_expires_at - job.lease_expires_at > timedelta(seconds=800)

    async def test_writes_with_an_old_lease_token_change_nothing(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        stale = uuid.uuid4()

        with pytest.raises(LeaseLostError):
            await jobs.update_progress(
                job_id=job.id,
                lease_token=stale,
                stage=JobStage.EXTRACTING,
                pages_done=1,
                pages_total=71,
            )
        with pytest.raises(LeaseLostError):
            await jobs.heartbeat(job_id=job.id, lease_token=stale, lease_seconds=90)
        with pytest.raises(LeaseLostError):
            await jobs.complete(job_id=job.id, lease_token=stale, summary=JobSummary())
        with pytest.raises(LeaseLostError):
            await jobs.fail(
                job_id=job.id,
                lease_token=stale,
                code=FailureCode.INTERNAL_ERROR,
                reason="stale",
            )

        assert await jobs.get(job.id) == job

    async def test_unknown_job_raises_not_found(self, jobs: PostgresJobQueue) -> None:
        with pytest.raises(JobNotFoundError):
            await jobs.get(uuid.uuid4())

    async def test_a_document_without_jobs_has_no_latest_job(
        self, jobs: PostgresJobQueue
    ) -> None:
        assert await jobs.latest_for_document(uuid.uuid4()) is None


def text_element(
    document_id: uuid.UUID, order: int, page: int = 1, **values: Any
) -> ExtractedElement:
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "document_id": document_id,
        "kind": ElementKind.PARAGRAPH,
        "page": page,
        "bbox": BoundingBox(left=10.5, top=20.25, right=300, bottom=64),
        "reading_order": order,
        "text": f"paragraph {order}",
    }
    return ExtractedElement(**(fields | values))


class TestElements:
    async def test_replacing_elements_stores_them_once_with_relationships(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        elements: PostgresElementRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None
        doc = job.document_id
        figure = text_element(
            doc,
            2,
            kind=ElementKind.IMAGE,
            text=None,
            image_key=f"figures/{doc}/x.png",
            image_class="engineering_drawing",
            labels=("V-12", "P-3"),
        )
        stored = [
            text_element(doc, 0, kind=ElementKind.HEADING, heading_level=2),
            text_element(
                doc, 1, kind=ElementKind.TABLE, text="| a |", table=(("a", "b"),)
            ),
            figure,
            text_element(doc, 3, page=2, origin=TextOrigin.RECOGNIZED, confidence=0.91),
        ]
        links = [
            ElementRelationship(
                source_id=stored[0].id, target_id=figure.id, kind=RelationshipKind.NEAR
            )
        ]

        for _ in range(2):
            await elements.replace_for_document(
                job_id=job.id,
                lease_token=job.lease_token,
                document_id=doc,
                elements=stored,
                relationships=links,
            )

        page = await elements.list_page(
            document_id=doc, page_number=None, kind=None, limit=10, cursor=None
        )
        assert list(page.items) == stored
        assert await elements.relationships_for([stored[0].id]) == tuple(links)
        # The target of a link sees it too, so an image lists its caption and text.
        assert await elements.relationships_for([figure.id]) == tuple(links)
        assert await elements.relationships_for([stored[1].id]) == ()
        assert await elements.get(document_id=doc, element_id=figure.id) == figure

    async def test_elements_are_paginated_and_filtered(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        elements: PostgresElementRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)
        assert job.lease_token is not None
        doc = job.document_id
        stored = [text_element(doc, n, page=1 + n % 2) for n in range(5)]
        await elements.replace_for_document(
            job_id=job.id,
            lease_token=job.lease_token,
            document_id=doc,
            elements=stored,
            relationships=(),
        )

        first = await elements.list_page(
            document_id=doc, page_number=1, kind=None, limit=2, cursor=None
        )
        second = await elements.list_page(
            document_id=doc,
            page_number=1,
            kind=ElementKind.PARAGRAPH,
            limit=2,
            cursor=first.next_cursor,
        )

        assert [e.reading_order for e in first.items] == [0, 2]
        assert [e.reading_order for e in second.items] == [4]
        assert second.next_cursor is None

    async def test_replacing_elements_with_an_old_lease_writes_nothing(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        elements: PostgresElementRepository,
        clock: FrozenClock,
    ) -> None:
        job = await claimed(jobs, documents, clock)

        with pytest.raises(LeaseLostError):
            await elements.replace_for_document(
                job_id=job.id,
                lease_token=uuid.uuid4(),
                document_id=job.document_id,
                elements=[text_element(job.document_id, 0)],
                relationships=(),
            )

        page = await elements.list_page(
            document_id=job.document_id,
            page_number=None,
            kind=None,
            limit=10,
            cursor=None,
        )
        assert page.items == ()

    async def test_unknown_element_raises_not_found(
        self, elements: PostgresElementRepository
    ) -> None:
        with pytest.raises(ElementNotFoundError):
            await elements.get(document_id=uuid.uuid4(), element_id=uuid.uuid4())


@pytest.mark.parametrize("cursor", ["bm90LWEtZGF0ZXxub3QtYS11dWlk", "%%%"])
async def test_invalid_document_cursors_are_rejected(
    documents: PostgresDocumentRepository, cursor: str
) -> None:
    with pytest.raises(InvalidCursorError):
        await documents.list_page(limit=2, cursor=cursor)


async def test_invalid_element_cursors_are_rejected(
    elements: PostgresElementRepository,
) -> None:
    with pytest.raises(InvalidCursorError):
        await elements.list_page(
            document_id=uuid.uuid4(),
            page_number=None,
            kind=None,
            limit=2,
            cursor="bm90LWEtbnVtYmVy",
        )


async def test_a_statement_over_the_timeout_is_a_storage_timeout(
    database_url: str,
) -> None:
    settings = DatabaseSettings(database_url=database_url, db_statement_timeout_ms=300)
    engine = create_engine(settings)

    with pytest.raises(StorageTimeoutError):
        async with connect(engine) as connection:
            await connection.execute(sa.text("SELECT pg_sleep(2)"))

    await engine.dispose()


class FailsBetweenInsertAndLookup(PostgresJobQueue):
    """Lets another worker fail the active job right after the conflicting insert."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.raced = False

    async def _active_job(
        self, connection: AsyncConnection, document_id: uuid.UUID
    ) -> IngestionJob | None:
        if not self.raced:
            self.raced = True
            async with self._engine.begin() as other:
                await other.execute(
                    sa.update(ingestion_jobs)
                    .where(ingestion_jobs.c.document_id == document_id)
                    .values(
                        status="failed",
                        failure_code="corrupt_document",
                        failure_reason="The PDF is damaged and cannot be read.",
                    )
                )
        return await super()._active_job(connection, document_id)


async def test_a_job_failing_during_enqueue_leaves_room_for_the_new_one(
    engine: AsyncEngine,
    documents: PostgresDocumentRepository,
    clock: FrozenClock,
) -> None:
    racing = FailsBetweenInsertAndLookup(engine)
    document, _ = await documents.register(new_document(clock))
    await racing.enqueue(new_job(clock, document))
    clock.advance(seconds=1)

    retry, created = await racing.enqueue(new_job(clock, document))

    assert created is True
    assert (await racing.latest_for_document(document.id)) == retry


class TestLeaseRecovery:
    async def test_an_expired_lease_is_reclaimed_under_a_new_token(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        document, _ = await documents.register(new_document(clock))
        await jobs.enqueue(new_job(clock, document))
        first = await jobs.claim(worker_id="crashed", lease_seconds=0)
        assert first is not None

        second = await jobs.claim(worker_id="healthy", lease_seconds=90)

        assert second is not None and second.id == first.id
        assert (second.attempt, second.status) == (2, JobStatus.PROCESSING)
        assert second.lease_token != first.lease_token
        assert second.worker_id == "healthy"

    async def test_the_claim_past_the_last_attempt_fails_the_job(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        document, _ = await documents.register(new_document(clock))
        job, _ = await jobs.enqueue(
            pending_job(clock, document_id=document.id, max_attempts=1)
        )
        assert await jobs.claim(worker_id="crashed", lease_seconds=0) is not None

        assert await jobs.claim(worker_id="healthy", lease_seconds=90) is None

        failed = await jobs.get(job.id)
        assert failed.status is JobStatus.FAILED
        assert failed.failure_code is FailureCode.INTERRUPTED_REPEATEDLY
        assert failed.failure_reason == (
            "Processing was interrupted repeatedly. Attempts used: 1 of 1."
        )

    async def test_a_heartbeat_keeps_the_job_from_being_reclaimed(
        self,
        jobs: PostgresJobQueue,
        documents: PostgresDocumentRepository,
        clock: FrozenClock,
    ) -> None:
        document, _ = await documents.register(new_document(clock))
        await jobs.enqueue(new_job(clock, document))
        job = await jobs.claim(worker_id="busy", lease_seconds=0)
        assert job is not None and job.lease_token is not None

        await jobs.heartbeat(
            job_id=job.id, lease_token=job.lease_token, lease_seconds=90
        )

        assert await jobs.claim(worker_id="other", lease_seconds=90) is None


async def test_a_lease_only_covers_the_elements_of_its_own_document(
    jobs: PostgresJobQueue,
    documents: PostgresDocumentRepository,
    elements: PostgresElementRepository,
    clock: FrozenClock,
) -> None:
    job = await claimed(jobs, documents, clock)
    assert job.lease_token is not None
    other, _ = await documents.register(new_document(clock, "9" * 64))

    with pytest.raises(DataInconsistencyError):
        await elements.replace_for_document(
            job_id=job.id,
            lease_token=job.lease_token,
            document_id=other.id,
            elements=[text_element(other.id, 0)],
            relationships=(),
        )


async def test_two_elements_of_a_document_cannot_share_a_reading_order(
    jobs: PostgresJobQueue,
    documents: PostgresDocumentRepository,
    elements: PostgresElementRepository,
    clock: FrozenClock,
) -> None:
    job = await claimed(jobs, documents, clock)
    assert job.lease_token is not None

    with pytest.raises(sa.exc.IntegrityError):
        await elements.replace_for_document(
            job_id=job.id,
            lease_token=job.lease_token,
            document_id=job.document_id,
            elements=[text_element(job.document_id, 0) for _ in range(2)],
            relationships=(),
        )


async def test_stored_summaries_survive_added_and_removed_fields(
    engine: AsyncEngine,
    jobs: PostgresJobQueue,
    documents: PostgresDocumentRepository,
    clock: FrozenClock,
) -> None:
    job = await claimed(jobs, documents, clock)
    async with engine.begin() as connection:
        await connection.execute(
            sa.update(ingestion_jobs)
            .where(ingestion_jobs.c.id == job.id)
            .values(summary={"pages": 3, "field_from_an_older_release": 1})
        )

    stored = await jobs.get(job.id)

    assert stored.summary == JobSummary(pages=3)
