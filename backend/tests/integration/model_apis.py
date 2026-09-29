"""respx routes that answer the OpenAI-compatible model APIs of the worker.

The integration tests run the real worker against real PostgreSQL and Qdrant, and only
the vision and embedding models are replaced, in the test process or in a worker
subprocess.
"""

import json

import httpx
import respx

# The models are replaced by respx routes, so this host is never contacted.
MODELS_URL = "http://models.test/v1/"


def route_model_apis(router: respx.MockRouter) -> None:
    """Answer the embedding and chat completion endpoints under ``MODELS_URL``.

    Embeddings are constant vectors derived from each text's length, and every figure
    gets the same description.

    Args:
        router: Router the routes are added to, before any pass-through route.
    """

    def embeddings(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [
            {"index": n, "embedding": [float(len(text) % 7 + 1)] * 1024}
            for n, text in enumerate(texts)
        ]
        return httpx.Response(200, json={"data": data})

    router.post(f"{MODELS_URL}embeddings").mock(side_effect=embeddings)
    router.post(f"{MODELS_URL}chat/completions").respond(
        json={"choices": [{"message": {"content": "A magneto wired to V-12."}}]}
    )
