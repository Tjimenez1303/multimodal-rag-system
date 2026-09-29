import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx
import stamina

from multimodal_rag.adapters.openai_compatible.reranker import (
    OpenAICompatibleRelevanceJudge,
)
from multimodal_rag.shared.errors import ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy
from tests.fakes import WordTokenCounter

BASE_URL = "http://models.test/v1/"
COMPLETIONS = f"{BASE_URL}chat/completions"
INSTRUCTION = "Judge whether the passage answers the question"
SYSTEM = (
    "Judge whether the Document meets the requirements based on the Query and the "
    'Instruct provided. Note that the answer can only be "yes" or "no".'
)
RETRY = RetryPolicy(
    attempts=3,
    initial_wait_seconds=0.01,
    max_wait_seconds=0.01,
    jitter_seconds=0,
    timeout_seconds=None,
)


@pytest.fixture(autouse=True)
def fast_retries() -> Iterator[None]:
    stamina.set_testing(True, attempts=3)
    yield
    stamina.set_testing(False)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        yield client


def judge_with(
    client: httpx.AsyncClient,
    *,
    instruction: str = INSTRUCTION,
    max_input_tokens: int = 2048,
) -> OpenAICompatibleRelevanceJudge:
    return OpenAICompatibleRelevanceJudge(
        client,
        model="ai/qwen3-reranker:0.6B",
        instruction=instruction,
        tokens=WordTokenCounter(),
        max_input_tokens=max_input_tokens,
        retry=RETRY,
    )


def judgement(**logprobs: float) -> dict[str, Any]:
    top = [
        {"token": token, "logprob": value, "bytes": []}
        for token, value in logprobs.items()
    ]
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": next(iter(logprobs), "")},
                "finish_reason": "length",
                "logprobs": {
                    "content": [{"token": "x", "logprob": -1.0, "top_logprobs": top}]
                },
            }
        ]
    }


def sent(call: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(call.request.content)
    return body


def document_of(body: dict[str, Any]) -> str:
    return str(body["messages"][1]["content"]).split("<Document>: ", 1)[1]


@respx.mock
async def test_each_passage_is_judged_with_the_model_card_prompt(
    client: httpx.AsyncClient,
) -> None:
    route = respx.post(COMPLETIONS).respond(json=judgement(yes=-0.1, no=-2.4))

    await judge_with(client).judge("Total Neto", ["Totales\nTotal Neto: $880,900.0"])

    body = sent(route.calls.last)
    assert body["model"] == "ai/qwen3-reranker:0.6B"
    assert body["max_tokens"] == 1
    assert body["temperature"] == 0
    assert body["logprobs"] is True
    assert body["top_logprobs"] == 20
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"] == [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"<Instruct>: {INSTRUCTION}\n<Query>: Total Neto\n"
                "<Document>: Totales\nTotal Neto: $880,900.0"
            ),
        },
    ]


@respx.mock
async def test_the_relevance_is_the_probability_of_yes_against_no(
    client: httpx.AsyncClient,
) -> None:
    respx.post(COMPLETIONS).respond(json=judgement(yes=-0.1, no=-2.4, Yes=-3.0))

    [relevance] = await judge_with(client).judge("Total Neto", ["Total Neto: 1"])

    expected = math.exp(-0.1) / (math.exp(-0.1) + math.exp(-2.4))
    assert relevance == pytest.approx(expected)


@pytest.mark.parametrize(
    ("logprobs", "expected"),
    [({"yes": -0.01, "maybe": -5.0}, 1.0), ({"no": -0.01, "maybe": -5.0}, 0.0)],
)
@respx.mock
async def test_a_token_missing_from_the_top_counts_as_probability_zero(
    client: httpx.AsyncClient, logprobs: dict[str, float], expected: float
) -> None:
    respx.post(COMPLETIONS).respond(json=judgement(**logprobs))

    assert await judge_with(client).judge("q", ["passage"]) == [expected]


@pytest.mark.parametrize(
    "answer",
    [
        judgement(maybe=-0.1, Yes=-1.0),
        judgement(yes=-1000.0, no=-1000.0),
        {"choices": [{"message": {"role": "assistant", "content": "yes"}}]},
    ],
    ids=["neither token", "both negligible", "no log probabilities"],
)
@respx.mock
async def test_an_answer_without_a_judgement_is_rejected(
    client: httpx.AsyncClient, answer: dict[str, Any]
) -> None:
    respx.post(COMPLETIONS).respond(json=answer)

    with pytest.raises(ProviderResponseError):
        await judge_with(client).judge("q", ["passage"])


@respx.mock
async def test_relevances_come_back_in_passage_order(
    client: httpx.AsyncClient,
) -> None:
    scores = {"first": -0.1, "second": -3.0, "third": -1.0}

    def reply(request: httpx.Request) -> httpx.Response:
        document = document_of(json.loads(request.content))
        return httpx.Response(200, json=judgement(yes=scores[document], no=-1.0))

    respx.post(COMPLETIONS).mock(side_effect=reply)

    relevances = await judge_with(client).judge("q", ["first", "second", "third"])

    expected = [math.exp(v) / (math.exp(v) + math.exp(-1.0)) for v in scores.values()]
    assert relevances == pytest.approx(expected)


@respx.mock
async def test_a_long_passage_is_shortened_to_fit_the_request(
    client: httpx.AsyncClient,
) -> None:
    route = respx.post(COMPLETIONS).respond(json=judgement(yes=-0.1, no=-2.4))
    passage = " ".join(f"row{n}" for n in range(500))

    await judge_with(client, max_input_tokens=80).judge("Total Neto", [passage])

    body = sent(route.calls.last)
    document = document_of(body)
    prompt = " ".join(message["content"] for message in body["messages"])
    assert document.startswith("row0 row1 row2")
    assert len(document.split()) < 80
    assert len(prompt.split()) <= 80


@respx.mock
async def test_a_passage_that_fits_is_sent_unchanged(
    client: httpx.AsyncClient,
) -> None:
    route = respx.post(COMPLETIONS).respond(json=judgement(yes=-0.1, no=-2.4))
    passage = "Totales\n\nTotal Neto:   $880,900.0"

    await judge_with(client).judge("Total Neto", [passage])

    assert document_of(sent(route.calls.last)) == passage


@respx.mock
async def test_no_passages_send_nothing(client: httpx.AsyncClient) -> None:
    route = respx.post(COMPLETIONS)

    assert await judge_with(client).judge("q", []) == []
    assert not route.called


@respx.mock
async def test_a_transient_failure_followed_by_success_recovers(
    client: httpx.AsyncClient,
) -> None:
    respx.post(COMPLETIONS).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=judgement(yes=-0.01, no=-6.0)),
        ]
    )

    [relevance] = await judge_with(client).judge("q", ["passage"])

    assert relevance > 0.99


@respx.mock
async def test_the_configured_instruction_reaches_every_request(
    client: httpx.AsyncClient,
) -> None:
    route = respx.post(COMPLETIONS).respond(json=judgement(yes=-0.1, no=-2.4))
    instruction = "Given a maintenance question, judge whether the passage answers it"

    await judge_with(client, instruction=instruction).judge("q", ["one", "two"])

    users = [sent(call)["messages"][1]["content"] for call in route.calls]
    assert len(users) == 2
    assert all(user.startswith(f"<Instruct>: {instruction}\n") for user in users)


@respx.mock
async def test_a_failed_passage_cancels_the_pending_requests(
    client: httpx.AsyncClient,
) -> None:
    async def reply(request: httpx.Request) -> httpx.Response:
        if document_of(json.loads(request.content)) == "rejected":
            return httpx.Response(400)
        await asyncio.sleep(5)
        return httpx.Response(200, json=judgement(yes=-0.1, no=-2.4))

    respx.post(COMPLETIONS).mock(side_effect=reply)
    started = time.perf_counter()

    with pytest.raises(ProviderResponseError):
        await judge_with(client).judge("q", ["slow", "rejected", "slower"])

    assert time.perf_counter() - started < 1
