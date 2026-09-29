import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import (
    provide_get_document,
    provide_list_documents,
)
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.ingestion.domain import Document
from multimodal_rag.ingestion.use_cases.library import GetDocument, ListDocuments
from tests.contract.contract import assert_matches_contract
from tests.fakes import (
    FrozenClock,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    finish_next,
    pending_job,
)

DOCUMENTS = "/api/v1/documents"
DOCUMENT = "/api/v1/documents/{document_id}"


@dataclass
class Api:
    client: TestClient
    clock: FrozenClock
    documents: InMemoryDocumentRepository
    jobs: InMemoryJobQueue

    async def register(self, name: str) -> Document:
        self.clock.advance(seconds=1)
        sha = hashlib.sha256(name.encode()).hexdigest()
        document, _ = await self.documents.register(
            Document(
                id=uuid.uuid4(),
                sha256=sha,
                file_name=name,
                size_bytes=2_048,
                page_count=4,
                blob_key=Document.blob_key_for(sha),
                created_at=self.clock.now(),
            )
        )
        return document

    async def upload(self, name: str) -> Document:
        document = await self.register(name)
        await self.jobs.enqueue(pending_job(self.clock, document_id=document.id))
        return document


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = FrozenClock()
    documents = InMemoryDocumentRepository()
    jobs = InMemoryJobQueue(clock)
    app = create_app(readiness_checks={}, routers=(documents_router,))
    app.dependency_overrides[provide_list_documents] = lambda: ListDocuments(
        documents=documents, jobs=jobs
    )
    app.dependency_overrides[provide_get_document] = lambda: GetDocument(
        documents=documents, jobs=jobs
    )
    with TestClient(RequestContextMiddleware(app)) as client:
        yield Api(client, clock, documents, jobs)


async def test_the_library_lists_documents_newest_first_across_pages(
    api: Api,
) -> None:
    await api.upload("first.pdf")
    await finish_next(api.jobs, succeed=True, pages=4)
    await api.upload("second.pdf")
    await api.register("third.pdf")

    first = api.client.get(DOCUMENTS, params={"limit": 2})
    second = api.client.get(
        DOCUMENTS, params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )

    for response in (first, second):
        assert response.status_code == 200
        assert_matches_contract(response, path=DOCUMENTS, method="get")
    third, newest = first.json()["items"]
    (oldest,) = second.json()["items"]
    assert [third["file_name"], newest["file_name"], oldest["file_name"]] == [
        "third.pdf",
        "second.pdf",
        "first.pdf",
    ]
    assert third["latest_job"] is None
    assert newest["latest_job"]["status"] == "pending"
    assert oldest["latest_job"]["status"] == "completed"
    assert (oldest["page_count"], oldest["size_bytes"]) == (4, 2_048)
    assert second.json()["next_cursor"] is None


async def test_a_cursor_not_issued_by_the_api_is_rejected(api: Api) -> None:
    response = api.client.get(DOCUMENTS, params={"cursor": "not-a-cursor"})

    assert response.status_code == 400
    assert_matches_contract(response, path=DOCUMENTS, method="get")
    assert response.json()["code"] == "invalid_cursor"


async def test_a_limit_above_the_maximum_is_rejected(api: Api) -> None:
    response = api.client.get(DOCUMENTS, params={"limit": 201})

    assert response.status_code == 400
    assert_matches_contract(response, path=DOCUMENTS, method="get")


async def test_a_document_is_returned_with_its_latest_job(api: Api) -> None:
    document = await api.upload("manual.pdf")

    response = api.client.get(DOCUMENT.format(document_id=document.id))

    assert response.status_code == 200
    assert_matches_contract(response, path=DOCUMENT, method="get")
    body = response.json()
    assert (body["id"], body["file_name"]) == (str(document.id), "manual.pdf")
    assert body["latest_job"]["document_id"] == str(document.id)


async def test_an_unknown_document_is_not_found(api: Api) -> None:
    response = api.client.get(DOCUMENT.format(document_id=uuid.uuid4()))

    assert response.status_code == 404
    assert_matches_contract(response, path=DOCUMENT, method="get")
    assert response.json()["code"] == "document_not_found"


async def test_a_malformed_document_id_is_a_bad_request(api: Api) -> None:
    response = api.client.get(DOCUMENT.format(document_id="not-a-uuid"))

    assert response.status_code == 400
    assert_matches_contract(response, path=DOCUMENT, method="get")
