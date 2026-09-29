"""Ports: the interfaces through which the answering core reaches the outside world.

Retrieval reuses the ingestion ports (embedder, vector index and repositories). The
ports below cover what only answering needs: the model that judges each retrieved unit,
the answer model, admission control and language identification. Every port has a
production adapter and a fake used by the tests.
"""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from multimodal_rag.answering.domain import GeneratedAnswer, GroundedPrompt


class RelevanceJudge(Protocol):
    """Model that judges whether each retrieved passage answers a question."""

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
                without a usable judgement.
        """
        ...


class AnswerGenerator(Protocol):
    """Model that writes an answer from a grounded prompt."""

    async def generate(self, prompt: GroundedPrompt) -> GeneratedAnswer:
        """Return the answer the model writes for a prompt.

        Args:
            prompt: Grounding rules, numbered sources and the question.

        Returns:
            The answer text with ``[n]`` markers and what the sources do not cover.

        Raises:
            ProviderUnavailableError: If the model stays unreachable after retries.
            ProviderTimeoutError: If the model keeps timing out after retries.
            ProviderResponseError: If the model rejects the request or returns an
                answer that does not follow the expected format.
        """
        ...


class AnswerSlots(Protocol):
    """Admission control that bounds how many questions run and wait at once."""

    def admit(self) -> AbstractAsyncContextManager[None]:
        """Hold a place for one question for the duration of a block.

        Entering the block waits for a free place, and leaving it frees the place,
        also when the question is cancelled.

        Returns:
            A context manager that holds the place.

        Raises:
            AnsweringBusyError: On entering, when every place is taken and the
                waiting line is full.
        """
        ...


class LanguageIdentifier(Protocol):
    """Identifies the language a short text is written in."""

    def identify(self, text: str, *, candidates: Sequence[str]) -> str:
        """Return the most likely language of a text among some candidates.

        Args:
            text: Text to classify, such as a question.
            candidates: ISO 639-1 codes the answer is chosen from, such as
                ``("en", "es")``.

        Returns:
            One of the candidates.
        """
        ...
