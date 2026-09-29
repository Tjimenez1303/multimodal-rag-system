"""``AnswerGenerator`` over the ``chat/completions`` route of the OpenAI API format.

The adapter only transports the prompt the core built. The output is constrained with a
``json_schema`` response format, which llama-server turns into a grammar, and is then
validated again, because the server generates unconstrained text when it cannot compile
a grammar. Thinking is disabled per request, as for figure descriptions. An answer cut
by the token limit is rejected, because its JSON is incomplete or its text unfinished.
"""

import logging
from typing import Any

import httpx
import pydantic

from multimodal_rag.adapters.openai_compatible.chat import ChatCompletion
from multimodal_rag.adapters.openai_compatible.transport import post_json
from multimodal_rag.answering.domain import GeneratedAnswer, GroundedPrompt
from multimodal_rag.answering.errors import AnswerModelResponseError
from multimodal_rag.shared.resilience import RetryPolicy

logger = logging.getLogger(__name__)

SERVICE = "answer model"
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "not_covered": {"type": "string"},
    },
    "required": ["answer", "not_covered"],
    "additionalProperties": False,
}


class _AnswerContent(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", strict=True)

    answer: str
    not_covered: str


class OpenAICompatibleAnswerGenerator:
    """Writes grounded answers with a model served in the OpenAI API format.

    Args:
        client: Client configured with the server's base URL and timeout.
        model: Model reference, such as ``ai/qwen3.5:9b``.
        max_tokens: Longest answer, in tokens.
        temperature: Sampling temperature.
        retry: Retry policy for transient failures.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        retry: RetryPolicy,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._retry = retry

    async def generate(self, prompt: GroundedPrompt) -> GeneratedAnswer:
        """Return the answer the model writes for a prompt.

        Args:
            prompt: Grounding rules, numbered sources and the question.

        Returns:
            The answer text and what the sources do not cover.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request.
            AnswerModelResponseError: If the answer does not follow the schema or was
                cut by the token limit.
        """
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "grounded_answer",
                    "strict": True,
                    "schema": ANSWER_SCHEMA,
                },
            },
        }
        completion = await post_json(
            self._client,
            "chat/completions",
            payload,
            answer=ChatCompletion,
            service=SERVICE,
            retry=self._retry,
        )
        if completion.reached_token_limit:
            logger.warning(
                "%s stopped at the token limit of %s", SERVICE, self._max_tokens
            )
            raise AnswerModelResponseError()
        try:
            content = _AnswerContent.model_validate_json(completion.content)
        except pydantic.ValidationError as error:
            raise AnswerModelResponseError() from error
        return GeneratedAnswer(text=content.answer, not_covered=content.not_covered)
