import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import provide_get_page_image
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.ingestion.domain import Document, ExtractedElement
from multimodal_rag.ingestion.use_cases.library import GetPageImage
from tests.builders import DOCUMENT_ID, SHA
from tests.contract.contract import assert_matches_contract
from tests.fakes import (
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    finish_next,
    pending_job,
)

PAGE = "/api/v1/documents/{document_id}/pages/{page_number}/image"
PNG = b"\x89PNG\r\n\x1a\n-page"


@dataclass
class Api:
    client: TestClient
    jobs: InMemoryJobQueue

    def url(self, page_number: object, document_id: object = DOCUMENT_ID) -> str:
        return PAGE.format(document_id=document_id, page_number=page_number)


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = FrozenClock()
    documents = InMemoryDocumentRepository()
    jobs = InMemoryJobQueue(clock)
    blobs = InMemoryBlobStorage()
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
    await blobs.save_bytes(
        ExtractedElement.page_image_key_for(document_id=DOCUMENT_ID, page_number=2),
        PNG,
    )
    app = create_app(readiness_checks={}, routers=(documents_router,))
    app.dependency_overrides[provide_get_page_image] = lambda: GetPageImage(
        documents=documents, jobs=jobs, blobs=blobs
    )
    with TestClient(RequestContextMiddleware(app)) as client:
        yield Api(client, jobs)


async def test_a_page_of_a_completed_document_is_served_as_png(api: Api) -> None:
    await finish_next(api.jobs, succeed=True)

    response = api.client.get(api.url(2))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG
    assert response.headers["x-request-id"]


def test_a_page_before_completion_is_a_conflict(api: Api) -> None:
    response = api.client.get(api.url(1))

    assert (response.status_code, response.json()["code"]) == (
        409,
        "ingestion_not_completed",
    )
    assert_matches_contract(response, path=PAGE, method="get")


@pytest.mark.parametrize(
    ("page_number", "document_id", "status", "code"),
    [
        (1, uuid.uuid4(), 404, "document_not_found"),
        (3, DOCUMENT_ID, 404, "page_not_found"),
        ("two", DOCUMENT_ID, 400, "invalid_request"),
        (0, DOCUMENT_ID, 400, "invalid_request"),
    ],
    ids=["unknown document", "past the last page", "not a number", "page 0"],
)
async def test_missing_pages_are_problem_details(
    api: Api, page_number: object, document_id: object, status: int, code: str
) -> None:
    await finish_next(api.jobs, succeed=True)

    response = api.client.get(api.url(page_number, document_id))

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert_matches_contract(response, path=PAGE, method="get")
