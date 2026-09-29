"""Domain model of question answering.

A question and its answer live only for the duration of a request and are never
stored. The types are immutable, and they reuse the ingestion entities for positions
and unit types. This module imports nothing outside the standard library and the
project's own domain and errors.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from multimodal_rag.answering.errors import InvalidQuestionError
from multimodal_rag.ingestion.domain import BoundingBox, UnitType


@dataclass(frozen=True, slots=True)
class Question:
    """A natural-language question, optionally restricted to some documents.

    Attributes:
        text: The trimmed question.
        document_ids: Documents the answer may come from, or ``None`` for every
            completed document.
    """

    text: str
    document_ids: tuple[uuid.UUID, ...] | None = None

    @classmethod
    def create(
        cls,
        text: str,
        *,
        document_ids: Sequence[uuid.UUID] | None = None,
        max_chars: int,
        max_documents: int,
    ) -> Question:
        """Build a question that follows the length and restriction rules.

        Args:
            text: The question as submitted.
            document_ids: Documents to restrict the answer to, or ``None``.
            max_chars: Longest question after trimming.
            max_documents: Most documents a question may be restricted to.

        Returns:
            The question with its text trimmed.

        Raises:
            InvalidQuestionError: If the trimmed text is empty or longer than
                ``max_chars``, or the restriction is empty, holds more than
                ``max_documents`` ids or repeats an id.
        """
        trimmed = text.strip()
        if not trimmed:
            raise InvalidQuestionError("The question is empty")
        if len(trimmed) > max_chars:
            raise InvalidQuestionError(
                f"The question has {len(trimmed)} characters, the limit is {max_chars}"
            )
        if document_ids is None:
            return cls(text=trimmed)
        if not 1 <= len(document_ids) <= max_documents:
            raise InvalidQuestionError(
                f"document_ids must hold 1 to {max_documents} ids"
            )
        if len(set(document_ids)) != len(document_ids):
            raise InvalidQuestionError("document_ids must not repeat an id")
        return cls(text=trimmed, document_ids=tuple(document_ids))


class AnswerStatus(StrEnum):
    """Whether the documents supported an answer."""

    ANSWERED = "answered"
    NOT_ENOUGH_INFORMATION = "not_enough_information"


class NotEnoughReason(StrEnum):
    """Why a question received no answer."""

    NO_SEARCHABLE_DOCUMENTS = "no_searchable_documents"
    NO_RELEVANT_CONTENT = "no_relevant_content"
    NOT_ANSWERED_BY_SOURCES = "not_answered_by_sources"
    NO_VALID_CITATIONS = "no_valid_citations"


@dataclass(frozen=True, slots=True)
class Citation:
    """A numbered reference from the answer text to the pages that support it.

    Attributes:
        number: Number of the ``[n]`` markers that refer to it, from 1.
        document_id: Document of the cited units.
        document_name: File name of that document.
        pages: Every page of the cited units, ascending.
        unit_ids: Supplied units merged into this citation because they share
            document and pages.
    """

    number: int
    document_id: uuid.UUID
    document_name: str
    pages: tuple[int, ...]
    unit_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class TableContent:
    """Rows of one part of a table, so a client can render it as a table.

    Attributes:
        page: Page of this part.
        rows: Cell text, header row first, as ingestion stored it.
    """

    page: int
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class RetrievedSource:
    """A retrieval unit supplied to the answer model for the question.

    Attributes:
        unit_id: Id of the retrieval unit.
        rank: Position in the fused ranking, from 1.
        similarity: Dense cosine similarity to the question.
        document_id: Document of the unit.
        document_name: File name of that document.
        section: Heading path, outermost first.
        pages: Pages the unit spans.
        content_type: Text, table or figure unit.
        excerpt: Beginning of the unit text.
        citation_number: Citation that cites this unit, if any.
        low_confidence_text: Whether an element was recognized below the
            low-confidence threshold.
        generated_description: Whether the unit includes a figure description
            written by a model.
        unverified_identifiers: Identifiers of that description missing from the
            figure's labels and caption.
        tables: Rows of each table element of a table unit.
        figure_ids: Non-decorative image elements associated with the unit.
    """

    unit_id: uuid.UUID
    rank: int
    similarity: float
    document_id: uuid.UUID
    document_name: str
    section: tuple[str, ...]
    pages: tuple[int, ...]
    content_type: UnitType
    excerpt: str
    citation_number: int | None
    low_confidence_text: bool
    generated_description: bool
    unverified_identifiers: tuple[str, ...]
    tables: tuple[TableContent, ...]
    figure_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class AnswerImage:
    """A figure returned with an answer.

    Attributes:
        element_id: Id of the image element.
        document_id: Document of the figure.
        document_name: File name of that document.
        page: Page of the figure.
        bbox: Position of the figure on the page.
        caption: Text of the element linked by ``caption_of``, if any.
        unit_id: Cited unit that brought the figure.
    """

    element_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page: int
    bbox: BoundingBox
    caption: str | None
    unit_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Answer:
    """The response to a question.

    Attributes:
        status: Whether the documents supported an answer.
        reason: Why there is no answer, only when not answered.
        text: Markdown with ``[n]`` markers when answered, otherwise a message in
            the question's language.
        not_covered: What the sources do not answer, for a partial answer.
        citations: Numbered citations, empty when not answered.
        sources: Every unit supplied to the answer model, in rank order.
        primary_image: The figure closest to the most relevant cited text.
        related_images: Other figures of the cited units, by relevance.
    """

    status: AnswerStatus
    reason: NotEnoughReason | None
    text: str
    not_covered: str | None = None
    citations: tuple[Citation, ...] = ()
    sources: tuple[RetrievedSource, ...] = ()
    primary_image: AnswerImage | None = None
    related_images: tuple[AnswerImage, ...] = ()

    @classmethod
    def not_enough(cls, reason: NotEnoughReason, text: str) -> Answer:
        """Build a not-enough-information outcome.

        Args:
            reason: Why the documents gave no answer.
            text: Message for the user, in the question's language.

        Returns:
            An answer without citations, sources or images.
        """
        return cls(status=AnswerStatus.NOT_ENOUGH_INFORMATION, reason=reason, text=text)


@dataclass(frozen=True, slots=True)
class GroundedPrompt:
    """Messages sent to the answer model, instructions apart from the sources.

    Attributes:
        system: Grounding rules.
        user: Numbered, fenced sources followed by the fenced question.
    """

    system: str
    user: str


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    """Validated output of the answer model.

    Attributes:
        text: Markdown answer with ``[n]`` source markers, empty when the sources
            do not answer the question.
        not_covered: What the sources do not answer, empty when nothing is missing.
    """

    text: str
    not_covered: str
