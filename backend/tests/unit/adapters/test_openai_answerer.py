import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx
import stamina

from multimodal_rag.adapters.openai_compatible.answerer import (
    OpenAICompatibleAnswerGenerator,
)
from multimodal_rag.answering.domain import GeneratedAnswer, GroundedPrompt
from multimodal_rag.answering.errors import AnswerModelResponseError
from multimodal_rag.shared.errors import ProviderUnavailableError
from multimodal_rag.shared.resilience import RetryPolicy

BASE_URL = "http://models.test/v1/"
COMPLETIONS = f"{BASE_URL}chat/completions"
RETRY = RetryPolicy(
    attempts=3,
    initial_wait_seconds=0.01,
    max_wait_seconds=0.01,
    jitter_seconds=0,
    timeout_seconds=None,
)
PROMPT = GroundedPrompt(system="Answer only from the sources.", user="[1] ...")


@pytest.fixture(autouse=True)
def fast_retries() -> Iterator[None]:
    stamina.set_testing(True, attempts=3)
    yield
    stamina.set_testing(False)


@pytest.fixture
async def generator() -> AsyncIterator[OpenAICompatibleAnswerGenerator]:
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        yield OpenAICompatibleAnswerGenerator(
            client, model="ai/qwen3.5:9b", max_tokens=800, temperature=0, retry=RETRY
        )


def reply(content: object) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


@respx.mock
async def test_the_request_carries_the_prompt_and_the_answer_schema(
    generator: OpenAICompatibleAnswerGenerator,
) -> None:
    route = respx.post(COMPLETIONS).respond(
        json=reply(json.dumps({"answer": "Poor regulation [1].", "not_covered": ""}))
    )

    await generator.generate(PROMPT)

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "ai/qwen3.5:9b"
    assert body["messages"] == [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": PROMPT.user},
    ]
    assert body["temperature"] == 0
    assert body["max_tokens"] == 800
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "not_covered": {"type": "string"},
        },
        "required": ["answer", "not_covered"],
        "additionalProperties": False,
    }


@respx.mock
async def test_a_valid_answer_becomes_a_generated_answer(
    generator: OpenAICompatibleAnswerGenerator,
) -> None:
    content = {"answer": "Solo la parte [1].", "not_covered": "El peso no consta."}
    respx.post(COMPLETIONS).respond(json=reply(json.dumps(content)))

    answer = await generator.generate(PROMPT)

    assert answer == GeneratedAnswer(
        text="Solo la parte [1].", not_covered="El peso no consta."
    )


@pytest.mark.parametrize(
    "content",
    [
        "Plain text instead of JSON.",
        json.dumps({"answer": "Missing the other field."}),
        json.dumps({"answer": 42, "not_covered": ""}),
        json.dumps({"answer": "x", "not_covered": "", "extra": "field"}),
        None,
    ],
    ids=["not json", "missing field", "wrong type", "extra field", "no content"],
)
@respx.mock
async def test_content_that_breaks_the_schema_is_an_invalid_response(
    generator: OpenAICompatibleAnswerGenerator, content: str | None
) -> None:
    route = respx.post(COMPLETIONS).respond(json=reply(content))

    with pytest.raises(AnswerModelResponseError):
        await generator.generate(PROMPT)

    assert route.call_count == 1


@respx.mock
async def test_an_unavailable_model_is_retried_then_reported(
    generator: OpenAICompatibleAnswerGenerator,
) -> None:
    route = respx.post(COMPLETIONS).mock(side_effect=[httpx.Response(503)] * 3)

    with pytest.raises(ProviderUnavailableError):
        await generator.generate(PROMPT)

    assert route.call_count == 3
