import base64
import io
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx
import stamina
from PIL import Image

from multimodal_rag.adapters.openai_compatible.describer import (
    OpenAICompatibleFigureDescriber,
)
from multimodal_rag.adapters.openai_compatible.embedder import (
    OpenAICompatibleEmbedder,
)
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from multimodal_rag.shared.resilience import RetryPolicy

BASE_URL = "http://models.test/v1/"
QUERY_INSTRUCTION = "Given a question, retrieve the passages that answer it"
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


def png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def chat_reply(content: object) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def embeddings_reply(vectors: list[list[float]]) -> dict[str, Any]:
    # Servers may list the items out of order, the index tells where each belongs.
    items = [
        {"object": "embedding", "index": index, "embedding": vector}
        for index, vector in enumerate(vectors)
    ]
    return {"object": "list", "data": list(reversed(items))}


class TestFigureDescriber:
    @pytest.fixture
    def describer(self, client: httpx.AsyncClient) -> OpenAICompatibleFigureDescriber:
        return OpenAICompatibleFigureDescriber(
            client, model="ai/qwen3.5:9b", retry=RETRY
        )

    @respx.mock
    async def test_sends_the_figure_its_context_and_thinking_disabled(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        route = respx.post(f"{BASE_URL}chat/completions").respond(
            json=chat_reply("  A magneto wired to valve V-12.\nLabels: V-12  ")
        )
        image = png(400, 300)

        text = await describer.describe(
            image_png=image,
            caption="Figure 1. Magneto circuit",
            context="The magneto fires the plugs.",
        )

        assert text == "A magneto wired to valve V-12.\nLabels: V-12"
        body = json.loads(route.calls.last.request.content)
        assert body["model"] == "ai/qwen3.5:9b"
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        [message] = body["messages"]
        prompt, picture = message["content"]
        assert "Figure 1. Magneto circuit" in prompt["text"]
        assert "The magneto fires the plugs." in prompt["text"]
        assert "language of the caption and surrounding text" in prompt["text"]
        assert "English" in prompt["text"]
        assert "verbatim" in prompt["text"]
        encoded = base64.b64encode(image).decode()
        assert picture["image_url"]["url"] == f"data:image/png;base64,{encoded}"

    @respx.mock
    async def test_the_language_instruction_follows_the_document_text(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        # A small model follows the language of an English prompt unless the language
        # rule comes again after the manual's text.
        route = respx.post(f"{BASE_URL}chat/completions").respond(
            json=chat_reply("Una bomba.")
        )

        await describer.describe(
            image_png=png(10, 10),
            caption="Figura 3. Bomba de combustible",
            context="La bomba alimenta la válvula V-12.",
        )

        prompt = json.loads(route.calls.last.request.content)["messages"][0]
        text = " ".join(prompt["content"][0]["text"].split())
        after_document = text.split("La bomba alimenta la válvula V-12.")[-1]
        assert "same language as the caption and surrounding text" in after_document
        assert "English" in after_document

    @respx.mock
    async def test_a_figure_without_text_is_described_in_english(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        route = respx.post(f"{BASE_URL}chat/completions").respond(
            json=chat_reply("A pump.")
        )

        await describer.describe(image_png=png(10, 10), caption=None, context=None)

        prompt = json.loads(route.calls.last.request.content)["messages"][0]
        assert "(none)" in prompt["content"][0]["text"]

    @respx.mock
    async def test_large_figures_are_downscaled_to_1280_pixels(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        route = respx.post(f"{BASE_URL}chat/completions").respond(
            json=chat_reply("A panel.")
        )

        await describer.describe(image_png=png(2560, 1000), caption=None, context=None)

        body = json.loads(route.calls.last.request.content)
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        assert sent.size == (1280, 500)

    @pytest.mark.parametrize(
        ("reply", "error"),
        [
            (httpx.Response(503), ProviderUnavailableError),
            (httpx.Response(429), ProviderUnavailableError),
            (httpx.ConnectError("refused"), ProviderUnavailableError),
            (httpx.ReadTimeout("slow"), ProviderTimeoutError),
        ],
        ids=["5xx", "429", "connection", "timeout"],
    )
    @respx.mock
    async def test_transient_failures_are_retried_then_reported(
        self,
        describer: OpenAICompatibleFigureDescriber,
        reply: httpx.Response | Exception,
        error: type[Exception],
    ) -> None:
        route = respx.post(f"{BASE_URL}chat/completions").mock(side_effect=[reply] * 3)

        with pytest.raises(error):
            await describer.describe(image_png=png(10, 10), caption=None, context=None)

        assert route.call_count == 3

    @respx.mock
    async def test_a_transient_failure_followed_by_success_recovers(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        respx.post(f"{BASE_URL}chat/completions").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, json=chat_reply("Ok.")),
            ]
        )

        text = await describer.describe(
            image_png=png(10, 10), caption=None, context=None
        )

        assert text == "Ok."

    @pytest.mark.parametrize(
        "reply",
        [
            httpx.Response(400, json={"error": "bad image"}),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"choices": []}),
            httpx.Response(200, json=chat_reply("   ")),
            httpx.Response(200, json=chat_reply(None)),
        ],
        ids=["4xx", "not json", "no choices", "blank", "no content"],
    )
    @respx.mock
    async def test_rejected_or_unusable_answers_are_not_retried(
        self, describer: OpenAICompatibleFigureDescriber, reply: httpx.Response
    ) -> None:
        route = respx.post(f"{BASE_URL}chat/completions").mock(return_value=reply)

        with pytest.raises(ProviderResponseError):
            await describer.describe(image_png=png(10, 10), caption=None, context=None)

        assert route.call_count == 1

    async def test_a_damaged_crop_is_a_data_inconsistency(
        self, describer: OpenAICompatibleFigureDescriber
    ) -> None:
        with pytest.raises(DataInconsistencyError):
            await describer.describe(image_png=b"not a png", caption=None, context=None)


class TestEmbedder:
    @pytest.fixture
    def embedder(self, client: httpx.AsyncClient) -> OpenAICompatibleEmbedder:
        return OpenAICompatibleEmbedder(
            client,
            model="ai/qwen3-embedding:0.6b",
            dimensions=3,
            batch_size=2,
            query_instruction=QUERY_INSTRUCTION,
            retry=RETRY,
        )

    @respx.mock
    async def test_inputs_are_sent_in_batches_and_returned_in_order(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        def reply(request: httpx.Request) -> httpx.Response:
            texts = json.loads(request.content)["input"]
            vectors = [[float(len(text)), 0.0, 1.0] for text in texts]
            return httpx.Response(200, json=embeddings_reply(vectors))

        route = respx.post(f"{BASE_URL}embeddings").mock(side_effect=reply)

        vectors = await embedder.embed(["a", "bb", "ccc"])

        assert vectors == [[1.0, 0.0, 1.0], [2.0, 0.0, 1.0], [3.0, 0.0, 1.0]]
        sent = [json.loads(call.request.content) for call in route.calls]
        assert [body["input"] for body in sent] == [["a", "bb"], ["ccc"]]
        assert {body["model"] for body in sent} == {"ai/qwen3-embedding:0.6b"}
        assert embedder.dimensions == 3

    async def test_nothing_to_embed_sends_nothing(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        assert await embedder.embed([]) == []

    @respx.mock
    async def test_a_vector_of_the_wrong_length_is_a_data_inconsistency(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        respx.post(f"{BASE_URL}embeddings").respond(json=embeddings_reply([[0.1, 0.2]]))

        with pytest.raises(DataInconsistencyError):
            await embedder.embed(["a"])

    @pytest.mark.parametrize(
        "body",
        [
            {"data": []},
            {"data": [{"index": 0, "embedding": "not a vector"}]},
            {"unexpected": True},
        ],
        ids=["missing vector", "not a vector", "no data"],
    )
    @respx.mock
    async def test_an_answer_of_the_wrong_shape_is_rejected(
        self, embedder: OpenAICompatibleEmbedder, body: dict[str, Any]
    ) -> None:
        respx.post(f"{BASE_URL}embeddings").respond(json=body)

        with pytest.raises(ProviderResponseError):
            await embedder.embed(["a"])

    @respx.mock
    async def test_an_unreachable_model_is_reported_after_retries(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        route = respx.post(f"{BASE_URL}embeddings").mock(
            side_effect=httpx.ConnectError("refused")
        )

        with pytest.raises(ProviderUnavailableError):
            await embedder.embed(["a"])

        assert route.call_count == 3

    @respx.mock
    async def test_a_query_is_sent_alone_with_the_retrieval_instruction(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        route = respx.post(f"{BASE_URL}embeddings").respond(
            json=embeddings_reply([[0.5, 0.25, 0.125]])
        )

        vector = await embedder.embed_query("What is code SPL-480?")

        assert vector == [0.5, 0.25, 0.125]
        assert json.loads(route.calls.last.request.content) == {
            "model": "ai/qwen3-embedding:0.6b",
            "input": [f"Instruct: {QUERY_INSTRUCTION}\nQuery:What is code SPL-480?"],
        }

    @respx.mock
    async def test_a_query_vector_of_the_wrong_length_is_a_data_inconsistency(
        self, embedder: OpenAICompatibleEmbedder
    ) -> None:
        respx.post(f"{BASE_URL}embeddings").respond(json=embeddings_reply([[0.1]]))

        with pytest.raises(DataInconsistencyError):
            await embedder.embed_query("x")
