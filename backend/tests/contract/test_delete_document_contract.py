import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import provide_delete_document
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.ingestion.domain import Document
from multimodal_rag.ingestion.use_cases.library import DeleteDocument
from tests.builders import DOCUMENT_ID, SHA
from tests.contract.contract import assert_matches_contract
from tests.fakes import (
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    InMemoryVectorIndex,
    finish_next,
    pending_job,
)

DOCUMENT = "/api/v1/documents/{document_id}"


@dataclass
class Api:
    client: TestClient
    jobs: InMemoryJobQueue
    documents: InMemoryDocumentRepository


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = FrozenClock()
    jobs = InMemoryJobQueue(clock)
    documents = InMemoryDocumentRepository(jobs=jobs)
    await documents.register(
        Document(
            id=DOCUMENT_ID,
            sha256=SHA,
            file_name="manual.pdf",
            size_bytes=100,
            page_count=2,
            blob_key=Document.blob_key_for(SHA),
            created_at=clock.now(),
        )
    )
    await jobs.enqueue(pending_job(clock, document_id=DOCUMENT_ID))
    app = create_app(readiness_checks={}, routers=(documents_router,))
    app.dependency_overrides[provide_delete_document] = lambda: DeleteDocument(
        documents=documents,
        jobs=jobs,
        index=InMemoryVectorIndex(),
        blobs=InMemoryBlobStorage(),
    )
    with TestClient(RequestContextMiddleware(app)) as client:
        yield Api(client, jobs, documents)


async def test_a_finished_document_is_deleted_with_no_content(api: Api) -> None:
    await finish_next(api.jobs, succeed=True)

    response = api.client.delete(DOCUMENT.format(document_id=DOCUMENT_ID))

    assert response.status_code == 204
    assert response.content == b""
    assert_matches_contract(response, path=DOCUMENT, method="delete")
    assert await api.documents.get_many([DOCUMENT_ID]) == ()


def test_a_document_being_ingested_is_a_conflict(api: Api) -> None:
    response = api.client.delete(DOCUMENT.format(document_id=DOCUMENT_ID))

    assert (response.status_code, response.json()["code"]) == (
        409,
        "ingestion_in_progress",
    )
    assert_matches_contract(response, path=DOCUMENT, method="delete")


@pytest.mark.parametrize(
    ("document_id", "status", "code"),
    [
        (uuid.uuid4(), 404, "document_not_found"),
        ("not-a-uuid", 400, "invalid_request"),
    ],
    ids=["unknown document", "malformed id"],
)
def test_bad_targets_are_problem_details(
    api: Api, document_id: object, status: int, code: str
) -> None:
    response = api.client.delete(DOCUMENT.format(document_id=document_id))

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert_matches_contract(response, path=DOCUMENT, method="delete")
