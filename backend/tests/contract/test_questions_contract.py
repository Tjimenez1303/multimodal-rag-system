from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import provide_answer_question
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_questions import questions_router
from multimodal_rag.answering.domain import GeneratedAnswer
from tests.contract.contract import assert_matches_contract
from tests.library import Library, document, element, unit

QUESTIONS = "/api/v1/questions"


@pytest.fixture
def library() -> Library:
    return Library()


@pytest.fixture
def client(library: Library) -> Iterator[TestClient]:
    app = create_app(readiness_checks={}, routers=(questions_router,))
    app.dependency_overrides[provide_answer_question] = lambda: library.ask()
    with TestClient(RequestContextMiddleware(app)) as client:
        yield client


async def test_an_answer_matches_the_contract(
    library: Library, client: TestClient
) -> None:
    manual = document("faa-powerplant-ch4.pdf")
    members = [element(manual, page=3), element(manual, page=4)]
    generator = unit(manual, "A series wound generator is never used.", members=members)
    await library.add(manual, members, [generator])
    library.answer(GeneratedAnswer(text="It is never used [1].", not_covered=""))

    response = client.post(
        QUESTIONS, json={"question": "Why is a series wound generator never used?"}
    )

    assert response.status_code == 200
    assert_matches_contract(response, path=QUESTIONS, method="post")
    body = response.json()
    assert (body["status"], body["reason"]) == ("answered", None)
    assert body["answer"] == "It is never used [1]."
    [citation] = body["citations"]
    assert citation["document_name"] == "faa-powerplant-ch4.pdf"
    assert citation["pages"] == [3, 4]
    [source] = body["sources"]
    assert (source["cited"], source["citation_number"]) == (True, 1)
    assert (body["primary_image"], body["related_images"]) == (None, [])


@pytest.mark.parametrize(
    "payload",
    [{}, {"question": 42}, {"question": "x", "unexpected": True}, ["not", "an object"]],
    ids=["missing question", "not a string", "unknown field", "not an object"],
)
def test_a_malformed_body_is_an_invalid_request(
    client: TestClient, payload: Any
) -> None:
    response = client.post(QUESTIONS, json=payload)

    assert response.status_code == 400
    assert_matches_contract(response, path=QUESTIONS, method="post")
    assert response.json()["code"] == "invalid_request"
