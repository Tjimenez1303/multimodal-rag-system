"""``Embedder`` over the ``embeddings`` route of the OpenAI API format.

Passages are sent in batches. The answer lists one item per input with its ``index``,
which gives the order, and every vector must have the collection's dimensions.
"""

from collections.abc import Sequence
from itertools import batched

import httpx
import pydantic

from multimodal_rag.adapters.openai_compatible.transport import post_json
from multimodal_rag.shared.errors import DataInconsistencyError, ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy

SERVICE = "embedding model"


class _Embedding(pydantic.BaseModel):
    index: int
    embedding: list[float]


class EmbeddingList(pydantic.BaseModel):
    """Part of an ``embeddings`` answer that the embedder reads.

    Attributes:
        data: One vector per input, each with the position of its input.
    """

    data: list[_Embedding]


class OpenAICompatibleEmbedder:
    """Turns passages into dense vectors with a model served in the OpenAI API format.

    Args:
        client: Client configured with the server's base URL and timeout.
        model: Model reference, such as ``ai/qwen3-embedding:0.6b``.
        dimensions: Length every vector must have.
        batch_size: Passages sent per request.
        retry: Retry policy for transient failures.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        dimensions: int,
        batch_size: int,
        retry: RetryPolicy,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._retry = retry

    @property
    def dimensions(self) -> int:
        """Length of every returned vector."""
        return self._dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per passage, in the same order.

        Args:
            texts: Passages to embed.

        Returns:
            The vectors, in the order of the passages.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request or answers with
                the wrong shape.
            DataInconsistencyError: If a vector has an unexpected length.
        """
        vectors: list[list[float]] = []
        for batch in batched(texts, self._batch_size, strict=False):
            answer = await post_json(
                self._client,
                "embeddings",
                {"model": self._model, "input": list(batch)},
                answer=EmbeddingList,
                service=SERVICE,
                retry=self._retry,
            )
            vectors += self._vectors(answer, expected=len(batch))
        return vectors

    def _vectors(self, answer: EmbeddingList, *, expected: int) -> list[list[float]]:
        if sorted(item.index for item in answer.data) != list(range(expected)):
            raise ProviderResponseError(f"The {SERVICE} answered the wrong vectors")
        vectors = [
            item.embedding for item in sorted(answer.data, key=lambda i: i.index)
        ]
        if any(len(vector) != self._dimensions for vector in vectors):
            raise DataInconsistencyError(
                f"The {SERVICE} returned vectors that are not {self._dimensions} long"
            )
        return vectors
