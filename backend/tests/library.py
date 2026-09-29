"""A small indexed library behind the answering use case, built on the port fakes."""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from multimodal_rag.answering.domain import GeneratedAnswer
from multimodal_rag.answering.use_cases.ask import AnsweringOptions, AnswerQuestion
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    Document,
    ElementKind,
    ExtractedElement,
    PagedBox,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.ingestion.ports import SearchHit
from tests.fakes import (
    FakeAnswerGenerator,
    FakeEmbedder,
    FrozenClock,
    InMemoryDocumentRepository,
    InMemoryElementRepository,
    InMemoryJobQueue,
    InMemoryVectorIndex,
)

BOX = BoundingBox(left=72, top=100, right=540, bottom=160)


def document(file_name: str) -> Document:
    """Build a document whose fingerprint derives from its name."""
    sha = hashlib.sha256(file_name.encode()).hexdigest()
    return Document(
        id=uuid.uuid4(),
        sha256=sha,
        file_name=file_name,
        size_bytes=2_048,
        page_count=40,
        blob_key=Document.blob_key_for(sha),
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


def element(
    owner: Document,
    *,
    page: int = 1,
    kind: ElementKind = ElementKind.PARAGRAPH,
    bbox: BoundingBox = BOX,
    **values: Any,
) -> ExtractedElement:
    """Build an element of a document, with text unless it is an image."""
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "document_id": owner.id,
        "kind": kind,
        "page": page,
        "bbox": bbox,
        "reading_order": 0,
    }
    if kind is not ElementKind.IMAGE:
        fields["text"] = "text"
    return ExtractedElement(**(fields | values))


def unit(
    owner: Document,
    text: str,
    *,
    members: Sequence[ExtractedElement],
    unit_type: UnitType = UnitType.TEXT,
    heading_path: tuple[str, ...] = ("Generators",),
    figure_ids: tuple[uuid.UUID, ...] = (),
) -> RetrievalUnit:
    """Build a retrieval unit over some elements of a document."""
    return RetrievalUnit(
        id=uuid.uuid4(),
        document_id=owner.id,
        unit_type=unit_type,
        text=text,
        heading_path=heading_path,
        pages=tuple(sorted({member.page for member in members})),
        element_ids=tuple(member.id for member in members),
        boxes=tuple(PagedBox(page=m.page, bbox=m.bbox) for m in members),
        figure_ids=figure_ids,
    )


def hit(retrieved: RetrievalUnit, *, similarity: float = 0.8) -> SearchHit:
    """Build a search hit for a unit."""
    return SearchHit(unit=retrieved, score=0.5, similarity=similarity)


@dataclass
class Library:
    """Documents, elements and published units served through the port fakes."""

    documents: InMemoryDocumentRepository = field(
        default_factory=InMemoryDocumentRepository
    )
    elements: InMemoryElementRepository = field(
        default_factory=lambda: InMemoryElementRepository(
            InMemoryJobQueue(FrozenClock())
        )
    )
    index: InMemoryVectorIndex = field(default_factory=InMemoryVectorIndex)
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)
    generator: FakeAnswerGenerator = field(default_factory=FakeAnswerGenerator)

    async def add(
        self,
        owner: Document,
        elements: Sequence[ExtractedElement],
        units: Sequence[RetrievalUnit],
        *,
        registered: bool = True,
    ) -> None:
        """Store a document with its elements and publish its units.

        Args:
            owner: Document of the elements and units.
            elements: Every element the units refer to.
            units: Units to index and publish.
            registered: Whether the document record is stored too.
        """
        if registered:
            await self.documents.register(owner)
        self.elements.elements.setdefault(owner.id, []).extend(elements)
        await self.index.upsert_units(units, [[0.0]] * len(units))
        await self.index.publish(owner.id)

    def answer(self, *replies: GeneratedAnswer | Exception) -> None:
        """Script the next replies of the answer model."""
        self.generator.replies.extend(replies)

    def ask(self, **options: Any) -> AnswerQuestion:
        """Build the use case over the fakes, with default options overridden."""
        defaults: dict[str, Any] = {
            "top_k": 8,
            "max_question_chars": 2000,
            "max_filter_documents": 20,
            "low_confidence_threshold": 0.90,
        }
        return AnswerQuestion(
            embedder=self.embedder,
            index=self.index,
            documents=self.documents,
            elements=self.elements,
            generator=self.generator,
            options=AnsweringOptions(**(defaults | options)),
        )
