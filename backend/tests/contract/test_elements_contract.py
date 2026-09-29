import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import (
    provide_get_element_image,
    provide_list_document_elements,
)
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.ingestion.domain import (
    Document,
    ElementKind,
    JobSummary,
    RelationshipKind,
    TextOrigin,
)
from multimodal_rag.ingestion.use_cases.library import (
    GetElementImage,
    ListDocumentElements,
)
from tests.builders import DOCUMENT_ID, SHA, link, make
from tests.contract.contract import assert_matches_contract
from tests.fakes import (
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryElementRepository,
    InMemoryJobQueue,
    claim_next,
    pending_job,
)

ELEMENTS = "/api/v1/documents/{document_id}/elements"
IMAGE = "/api/v1/documents/{document_id}/images/{element_id}"
PNG = b"\x89PNG\r\n\x1a\n-figure"
FIGURE = make(
    0,
    ElementKind.IMAGE,
    image_key="figures/doc/figure.png",
    image_class="engineering_drawing",
    labels=("V-12",),
)
CAPTION = make(1, ElementKind.CAPTION, text="Figure 1. Pump")
TABLE = make(2, ElementKind.TABLE, page=2)
SCANNED = make(3, page=2, origin=TextOrigin.RECOGNIZED, confidence=0.91)


@dataclass
class Api:
    client: TestClient
    jobs: InMemoryJobQueue
    elements: InMemoryElementRepository

    def elements_url(self, document_id: uuid.UUID = DOCUMENT_ID) -> str:
        return ELEMENTS.format(document_id=document_id)

    def image_url(self, element_id: uuid.UUID) -> str:
        return IMAGE.format(document_id=DOCUMENT_ID, element_id=element_id)

    async def complete(self) -> None:
        job = await claim_next(self.jobs)
        assert job.lease_token is not None
        await self.elements.replace_for_document(
            job_id=job.id,
            lease_token=job.lease_token,
            document_id=DOCUMENT_ID,
            elements=[FIGURE, CAPTION, TABLE, SCANNED],
            relationships=[link(CAPTION, FIGURE, RelationshipKind.CAPTION_OF)],
        )
        await self.jobs.complete(
            job_id=job.id, lease_token=job.lease_token, summary=JobSummary()
        )


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    clock = FrozenClock()
    documents = InMemoryDocumentRepository()
    jobs = InMemoryJobQueue(clock)
    elements = InMemoryElementRepository(jobs)
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
    await blobs.save_bytes("figures/doc/figure.png", PNG)
    app = create_app(readiness_checks={}, routers=(documents_router,))
    app.dependency_overrides[provide_list_document_elements] = lambda: (
        ListDocumentElements(documents=documents, jobs=jobs, elements=elements)
    )
    app.dependency_overrides[provide_get_element_image] = lambda: GetElementImage(
        elements=elements, blobs=blobs
    )
    with TestClient(RequestContextMiddleware(app)) as client:
        yield Api(client, jobs, elements)


async def test_elements_of_a_completed_document_match_the_contract(api: Api) -> None:
    await api.complete()

    response = api.client.get(api.elements_url())

    assert response.status_code == 200
    assert_matches_contract(response, path=ELEMENTS, method="get")
    image, caption, table, scanned = response.json()["items"]
    assert image["bbox"]["origin"] == "top_left"
    assert image["image_url"] == api.image_url(FIGURE.id)
    assert image["labels"] == ["V-12"]
    assert image["relationships"] == [
        {
            "source_id": str(CAPTION.id),
            "target_id": str(FIGURE.id),
            "kind": "caption_of",
        }
    ]
    assert caption["image_url"] is None
    assert table["table"] == {
        "rows": 2,
        "columns": 2,
        "cells": [["Part", "Code"], ["row 2", "A-1"]],
    }
    assert (scanned["origin"], scanned["confidence"]) == ("recognized", 0.91)


async def test_elements_are_filtered_and_paginated(api: Api) -> None:
    await api.complete()

    first = api.client.get(api.elements_url(), params={"page": 2, "limit": 1})
    second = api.client.get(
        api.elements_url(),
        params={"page": 2, "limit": 1, "cursor": first.json()["next_cursor"]},
    )
    images = api.client.get(api.elements_url(), params={"kind": "image"})

    assert [e["kind"] for e in first.json()["items"]] == ["table"]
    assert [e["kind"] for e in second.json()["items"]] == ["paragraph"]
    assert second.json()["next_cursor"] is None
    assert [e["id"] for e in images.json()["items"]] == [str(FIGURE.id)]
    for response in (first, second, images):
        assert_matches_contract(response, path=ELEMENTS, method="get")


def test_elements_before_completion_are_a_conflict(api: Api) -> None:
    response = api.client.get(api.elements_url())

    assert response.status_code == 409
    assert response.json()["code"] == "ingestion_not_completed"
    assert_matches_contract(response, path=ELEMENTS, method="get")


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        (ELEMENTS.format(document_id=uuid.uuid4()), 404, "document_not_found"),
        (ELEMENTS.format(document_id="not-a-uuid"), 400, "invalid_request"),
        (ELEMENTS.format(document_id=DOCUMENT_ID) + "?page=0", 400, "invalid_request"),
        (
            ELEMENTS.format(document_id=DOCUMENT_ID) + "?kind=chart",
            400,
            "invalid_request",
        ),
        (
            ELEMENTS.format(document_id=DOCUMENT_ID) + "?limit=201",
            400,
            "invalid_request",
        ),
        (
            ELEMENTS.format(document_id=DOCUMENT_ID) + "?cursor=%%%",
            400,
            "invalid_cursor",
        ),
    ],
    ids=["unknown", "bad id", "page 0", "bad kind", "limit", "bad cursor"],
)
async def test_invalid_element_requests_are_problem_details(
    api: Api, url: str, status: int, code: str
) -> None:
    await api.complete()

    response = api.client.get(url)

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert_matches_contract(response, path=ELEMENTS, method="get")


async def test_an_image_is_served_as_png(api: Api) -> None:
    await api.complete()

    response = api.client.get(api.image_url(FIGURE.id))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    ("element_id", "status", "code"),
    [
        (str(CAPTION.id), 404, "image_not_found"),
        (str(uuid.uuid4()), 404, "element_not_found"),
        ("not-a-uuid", 400, "invalid_request"),
    ],
)
async def test_missing_images_are_problem_details(
    api: Api, element_id: str, status: int, code: str
) -> None:
    await api.complete()

    response = api.client.get(
        IMAGE.format(document_id=DOCUMENT_ID, element_id=element_id)
    )

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert_matches_contract(response, path=IMAGE, method="get")
