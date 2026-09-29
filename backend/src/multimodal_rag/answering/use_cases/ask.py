"""Answering one question from the retrieved units of the completed documents.

The answer model is asked only when a retrieved unit passes the relevance gate. Every
other outcome where the documents do not support an answer, whether decided before or
after the model call, is a not-enough-information answer with a reason and no
citations, sources or images. An answer the model wrote without any source marker is
attributed to the supplied units statement by statement before its citations are
checked.
"""

import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from multimodal_rag.answering.attribution import attribute, find_statements
from multimodal_rag.answering.citations import (
    CitedText,
    has_markers,
    resolve_citations,
)
from multimodal_rag.answering.domain import (
    Answer,
    AnswerStatus,
    GeneratedAnswer,
    NotEnoughReason,
    Question,
)
from multimodal_rag.answering.messages import SUPPORTED_LANGUAGES, not_enough_message
from multimodal_rag.answering.ports import AnswerGenerator, LanguageIdentifier
from multimodal_rag.answering.prompting import build_prompt
from multimodal_rag.answering.relevance import distinct_hits, passes_gate
from multimodal_rag.answering.sources import assemble_sources, elements_of
from multimodal_rag.ingestion.domain import ExtractedElement
from multimodal_rag.ingestion.ports import (
    DocumentRepository,
    ElementRepository,
    Embedder,
    SearchHit,
    VectorIndex,
)
from multimodal_rag.shared.errors import DataInconsistencyError

logger = logging.getLogger(__name__)

# Hits searched per supplied unit, so that dropping repeated texts keeps the slots full.
SEARCH_OVERFETCH = 2


@dataclass(frozen=True, slots=True)
class AnsweringOptions:
    """Settings of the answering use case.

    Attributes:
        top_k: Retrieval units supplied to the answer model.
        max_question_chars: Longest question, after trimming.
        max_filter_documents: Most documents a question may be restricted to.
        low_confidence_threshold: Recognition confidence below which a source is
            flagged as low-confidence recognized text.
        min_similarity: Lowest dense similarity that lets a unit pass the relevance
            gate.
        attribution_min_score: Lowest match that attributes a statement of an answer
            written without markers.
    """

    top_k: int
    max_question_chars: int
    max_filter_documents: int
    low_confidence_threshold: float
    min_similarity: float
    attribution_min_score: float


@dataclass
class _Timings:
    search_ms: float = 0.0
    generation_ms: float = 0.0


class AnswerQuestion:
    """Answers a question only from the units retrieved for it.

    Each question is answered on its own: nothing from an earlier question is kept.

    Args:
        embedder: Embedding model that turns the question into a query vector.
        index: Hybrid index of retrieval units.
        documents: Document persistence, for the names of cited documents.
        elements: Element persistence, for the flags of each source.
        generator: Answer model.
        languages: Identifies the question's language for the fixed messages.
        options: Limits and thresholds of the use case.
    """

    def __init__(
        self,
        *,
        embedder: Embedder,
        index: VectorIndex,
        documents: DocumentRepository,
        elements: ElementRepository,
        generator: AnswerGenerator,
        languages: LanguageIdentifier,
        options: AnsweringOptions,
    ) -> None:
        self._embedder = embedder
        self._index = index
        self._documents = documents
        self._elements = elements
        self._generator = generator
        self._languages = languages
        self._options = options

    async def __call__(
        self, text: str, *, document_ids: Sequence[uuid.UUID] | None = None
    ) -> Answer:
        """Answer a question from the completed documents.

        Args:
            text: The question as submitted.
            document_ids: Documents to restrict the answer to, or ``None``.

        Returns:
            The answer with its citations and sources, or a not-enough-information
            outcome with its reason.

        Raises:
            InvalidQuestionError: If the question is empty or too long.
            DataInconsistencyError: If a retrieved unit refers to a missing document
                or element.
        """
        question = Question.create(
            text,
            document_ids=document_ids,
            max_chars=self._options.max_question_chars,
            max_documents=self._options.max_filter_documents,
        )
        timings = _Timings()
        answer = await self._answer(question, timings)
        logger.info(
            "question answered: outcome %s, reason %s, units %s, cited %s, "
            "search_ms %.1f, generation_ms %.1f",
            answer.status,
            answer.reason,
            len(answer.sources),
            len(answer.citations),
            timings.search_ms,
            timings.generation_ms,
        )
        return answer

    async def _answer(self, question: Question, timings: _Timings) -> Answer:
        started = time.perf_counter()
        hits = await self._search(question)
        timings.search_ms = (time.perf_counter() - started) * 1000
        if not hits:
            return self._not_enough(question, NotEnoughReason.NO_SEARCHABLE_DOCUMENTS)
        if not passes_gate(
            hits, min_similarity=self._options.min_similarity, question=question.text
        ):
            return self._not_enough(question, NotEnoughReason.NO_RELEVANT_CONTENT)
        names = await self._document_names(hits)
        elements = await self._elements_of(hits)
        started = time.perf_counter()
        prompt = build_prompt(question, hits, document_names=names)
        generated = await self._generator.generate(prompt)
        timings.generation_ms = (time.perf_counter() - started) * 1000
        if not generated.text.strip():
            return self._not_enough(
                question, NotEnoughReason.NOT_ANSWERED_BY_SOURCES, generated
            )
        cited = await self._cited(generated.text, hits, names)
        if not cited.citations:
            return self._not_enough(
                question, NotEnoughReason.NO_VALID_CITATIONS, generated
            )
        return self._grounded(generated, cited, hits, names, elements)

    async def _search(self, question: Question) -> list[SearchHit]:
        vector = await self._embedder.embed_query(question.text)
        hits = await self._index.search_hybrid(
            query_text=question.text,
            query_vector=vector,
            limit=self._options.top_k * SEARCH_OVERFETCH,
            document_ids=question.document_ids,
        )
        return distinct_hits(hits, limit=self._options.top_k)

    async def _document_names(self, hits: Sequence[SearchHit]) -> dict[uuid.UUID, str]:
        wanted = list(dict.fromkeys(hit.unit.document_id for hit in hits))
        found = {d.id: d.file_name for d in await self._documents.get_many(wanted)}
        missing = [document_id for document_id in wanted if document_id not in found]
        if missing:
            raise DataInconsistencyError(
                f"Indexed units refer to missing documents: {missing}"
            )
        return found

    async def _elements_of(
        self, hits: Sequence[SearchHit]
    ) -> dict[uuid.UUID, ExtractedElement]:
        wanted = list(dict.fromkeys(i for hit in hits for i in elements_of(hit.unit)))
        return {e.id: e for e in await self._elements.get_many(wanted)}

    async def _cited(
        self, text: str, hits: Sequence[SearchHit], names: dict[uuid.UUID, str]
    ) -> CitedText:
        units = [hit.unit for hit in hits]
        # An answer that cites only unsupplied sources invented them, so it is kept.
        if not has_markers(text):
            text = await self._attributed(text, hits)
        return resolve_citations(text, units, document_names=names)

    async def _attributed(self, text: str, hits: Sequence[SearchHit]) -> str:
        statements = find_statements(text)
        if not statements:
            return text
        units = [hit.unit for hit in hits]
        vectors = await self._embedder.embed(
            [s.text for s in statements] + [unit.embedding_text for unit in units]
        )
        attribution = attribute(
            text,
            statements,
            units=units,
            statement_vectors=vectors[: len(statements)],
            unit_vectors=vectors[len(statements) :],
            min_score=self._options.attribution_min_score,
        )
        logger.info(
            "answer without markers: attributed %s of %s statements",
            attribution.attributed,
            len(statements),
        )
        return attribution.text

    def _grounded(
        self,
        generated: GeneratedAnswer,
        cited: CitedText,
        hits: Sequence[SearchHit],
        names: dict[uuid.UUID, str],
        elements: dict[uuid.UUID, ExtractedElement],
    ) -> Answer:
        return Answer(
            status=AnswerStatus.ANSWERED,
            reason=None,
            text=cited.text,
            not_covered=generated.not_covered.strip() or None,
            citations=cited.citations,
            sources=assemble_sources(
                hits,
                elements=elements,
                document_names=names,
                citation_numbers=cited.numbers,
                low_confidence_threshold=self._options.low_confidence_threshold,
            ),
        )

    def _not_enough(
        self,
        question: Question,
        reason: NotEnoughReason,
        generated: GeneratedAnswer | None = None,
    ) -> Answer:
        # The model's own sentence names what is missing, in the question's language.
        explanation = generated.not_covered.strip() if generated else ""
        if not explanation:
            language = self._languages.identify(
                question.text, candidates=SUPPORTED_LANGUAGES
            )
            explanation = not_enough_message(reason, language=language)
        return Answer.not_enough(reason, explanation)
