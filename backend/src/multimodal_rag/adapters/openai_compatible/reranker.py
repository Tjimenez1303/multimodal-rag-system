"""``RelevanceJudge`` over the ``chat/completions`` route of the OpenAI API format.

Qwen3-Reranker judges a passage by answering "yes" or "no" to a fixed judging prompt,
and its model card defines the relevance as the probability of "yes" against "no" for
that single token. Each passage is sent as one chat request that asks for one token with
its log probabilities, and the relevance is computed from the log probabilities of
``yes`` and ``no``. The chat template of the served model adds the empty thinking block
the model card appends when thinking is disabled.

The ``/rerank`` route is not used, because llama.cpp applies a fixed web-search
instruction there, while this project's instruction is what tells a passage that answers
the question from one that only shares its topic.

Passages that do not fit one judging request are shortened to a prefix, which keeps
their headings, with the tokenizer the reranker shares with the embedding model.
"""

import asyncio
import logging
import math
from collections.abc import Sequence

import httpx

from multimodal_rag.adapters.openai_compatible.chat import ChatCompletion
from multimodal_rag.adapters.openai_compatible.transport import post_json
from multimodal_rag.ingestion.ports import TokenCounter
from multimodal_rag.shared.errors import ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy

logger = logging.getLogger(__name__)

SERVICE = "reranker"
# The judging prompt of the Qwen3-Reranker model card.
SYSTEM = (
    "Judge whether the Document meets the requirements based on the Query and the "
    'Instruct provided. Note that the answer can only be "yes" or "no".'
)
# Candidates of the first token the server returns with their log probabilities.
TOP_LOGPROBS = 20
# The chat markers the served template adds around the two messages, counted toward
# the length of a request.
_TEMPLATE = (
    "<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)


class OpenAICompatibleRelevanceJudge:
    """Judges passages with a Qwen3-Reranker model served in the OpenAI API format.

    Args:
        client: Client configured with the server's base URL and timeout.
        model: Model reference, such as ``ai/qwen3-reranker:0.6B``.
        instruction: Task sentence the model judges each passage with.
        tokens: Tokenizer shared with the model, used to shorten long passages.
        max_input_tokens: Longest judging request, one slot of the model's context.
        retry: Retry policy for transient failures.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        instruction: str,
        tokens: TokenCounter,
        max_input_tokens: int,
        retry: RetryPolicy,
    ) -> None:
        self._client = client
        self._model = model
        self._instruction = instruction
        self._tokens = tokens
        self._max_input_tokens = max_input_tokens
        self._retry = retry

    async def judge(self, question: str, passages: Sequence[str]) -> list[float]:
        """Return, for each passage, the probability that it answers the question.

        Args:
            question: The question as the technician asked it.
            passages: Texts of the retrieved units, headings first.

        Returns:
            One relevance from 0 to 1 per passage, in the same order.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request or answers
                without the log probabilities of ``yes`` or ``no``.
        """
        # Nothing to judge
        if not passages:
            return []

        # Tokens left for the passage once the prompt template is counted
        budget = self._max_input_tokens - self._tokens.count(
            _TEMPLATE.format(system=SYSTEM, user=self._user(question, ""))
        )
        try:
            # Judge every passage concurrently, each in its own request
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(
                        self._judge_one(
                            question, self._tokens.truncate(passage, max(budget, 0))
                        )
                    )
                    for passage in passages
                ]
        except ExceptionGroup as failure:
            # The group cancels the other requests and wraps every error that arrived
            # before, so the first one is raised as itself for the failure mapping.
            error = failure.exceptions[0]
            raise error from error.__cause__
        return [task.result() for task in tasks]

    async def _judge_one(self, question: str, passage: str) -> float:
        # Ask for a single token with the log probabilities of its candidates
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": self._user(question, passage)},
            ],
            "max_tokens": 1,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": TOP_LOGPROBS,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        # Call chat/completions with retries on transient failures
        completion = await post_json(
            self._client,
            "chat/completions",
            payload,
            answer=ChatCompletion,
            service=SERVICE,
            retry=self._retry,
        )
        return _relevance(completion.first_token_logprobs)

    def _user(self, question: str, passage: str) -> str:
        return (
            f"<Instruct>: {self._instruction}\n<Query>: {question}\n"
            f"<Document>: {passage}"
        )


def _relevance(logprobs: dict[str, float] | None) -> float:
    # A token outside the listed candidates has a negligible probability, taken as 0.
    if logprobs is None or ("yes" not in logprobs and "no" not in logprobs):
        logger.warning("%s answered without a yes or no judgement", SERVICE)
        raise ProviderResponseError(f"The {SERVICE} answered without a judgement")

    # Turn log probabilities into the probability of yes against no
    yes = math.exp(logprobs["yes"]) if "yes" in logprobs else 0.0
    no = math.exp(logprobs["no"]) if "no" in logprobs else 0.0
    if yes + no == 0:
        raise ProviderResponseError(f"The {SERVICE} answered an empty judgement")
    return yes / (yes + no)
