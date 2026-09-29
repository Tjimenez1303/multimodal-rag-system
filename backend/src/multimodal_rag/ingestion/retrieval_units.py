"""Structure-aware retrieval units built from the elements of a document.

Units break at headings, tables and figures. Paragraphs under the same headings merge up
to a token ceiling measured on the contextualized text, heading path included. A
paragraph above the ceiling splits at sentence ends, and a table or a chain of table
parts is never split.
"""

import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from multimodal_rag.ingestion.domain import (
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PagedBox,
    RelationshipKind,
    RetrievalUnit,
    UnitType,
    unit_id_for,
)
from multimodal_rag.ingestion.ports import TokenCounter
from multimodal_rag.ingestion.relationships import repeats_header
from multimodal_rag.shared.text import split_sentences

_FLOWING_KINDS = frozenset(
    {ElementKind.PARAGRAPH, ElementKind.LIST_ITEM, ElementKind.CAPTION}
)
_CAPTION_LINKS = frozenset({RelationshipKind.CAPTION_OF, RelationshipKind.TITLE_OF})
# The line under a Markdown table header, such as |---|:--:|.
_HEADER_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")


def build_units(
    *,
    document_id: uuid.UUID,
    document_sha256: str,
    elements: Sequence[ExtractedElement],
    relationships: Sequence[ElementRelationship],
    counter: TokenCounter,
    max_tokens: int,
) -> tuple[RetrievalUnit, ...]:
    """Group the elements of a document into retrieval units.

    Args:
        document_id: Document the units belong to.
        document_sha256: Fingerprint used to derive stable unit ids.
        elements: Elements of the whole document.
        relationships: Relationships of the document.
        counter: Tokenizer of the embedding model.
        max_tokens: Ceiling of a text unit, heading path included.

    Returns:
        The units in reading order.
    """
    builder = _Builder(
        document_id=document_id,
        sha256=document_sha256,
        links=_Links.of(relationships),
        counter=counter,
        max_tokens=max_tokens,
        elements={element.id: element for element in elements},
    )
    for element in sorted(elements, key=lambda e: e.reading_order):
        builder.add(element)
    builder.flush()
    return tuple(builder.units)


@dataclass(frozen=True, slots=True)
class _Links:
    captions: Mapping[uuid.UUID, tuple[uuid.UUID, ...]]
    caption_ids: frozenset[uuid.UUID]
    next_part: Mapping[uuid.UUID, uuid.UUID]
    continuation_ids: frozenset[uuid.UUID]
    near: Mapping[uuid.UUID, tuple[uuid.UUID, ...]]

    @classmethod
    def of(cls, relationships: Sequence[ElementRelationship]) -> _Links:
        captions: dict[uuid.UUID, list[uuid.UUID]] = {}
        near: dict[uuid.UUID, list[uuid.UUID]] = {}
        next_part: dict[uuid.UUID, uuid.UUID] = {}
        for link in relationships:
            if link.kind in _CAPTION_LINKS:
                captions.setdefault(link.target_id, []).append(link.source_id)
            elif link.kind is RelationshipKind.NEAR:
                near.setdefault(link.source_id, []).append(link.target_id)
            elif link.kind is RelationshipKind.CONTINUES:
                next_part[link.target_id] = link.source_id
        return cls(
            captions={key: tuple(value) for key, value in captions.items()},
            caption_ids=frozenset(c for ids in captions.values() for c in ids),
            next_part=next_part,
            continuation_ids=frozenset(next_part.values()),
            near={key: tuple(value) for key, value in near.items()},
        )


@dataclass
class _Builder:
    document_id: uuid.UUID
    sha256: str
    links: _Links
    counter: TokenCounter
    max_tokens: int
    elements: Mapping[uuid.UUID, ExtractedElement]
    units: list[RetrievalUnit] = field(default_factory=list)
    headings: dict[int, str] = field(default_factory=dict)
    pending: list[ExtractedElement] = field(default_factory=list)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.headings[level] for level in sorted(self.headings))

    def add(self, element: ExtractedElement) -> None:
        if element.kind is ElementKind.HEADING:
            self.flush()
            level = element.heading_level or 1
            # A heading replaces every heading at its level or deeper.
            self.headings = {k: v for k, v in self.headings.items() if k < level}
            self.headings[level] = element.text or ""
        elif element.kind is ElementKind.TABLE:
            self.flush()
            if element.id not in self.links.continuation_ids:
                self._table(element)
        elif element.kind is ElementKind.IMAGE and not element.is_decorative:
            self.flush()
            self._figure(element)
        elif (
            element.kind in _FLOWING_KINDS
            and element.id not in self.links.caption_ids
            and element.text
        ):
            self._flow(element)

    def flush(self) -> None:
        if self.pending:
            members = tuple(self.pending)
            self.pending = []
            text = "\n".join(member.text or "" for member in members)
            self._emit(UnitType.TEXT, f"text:{members[0].id}", text, members)

    def _flow(self, element: ExtractedElement) -> None:
        if self._tokens([*self.pending, element]) <= self.max_tokens:
            self.pending.append(element)
            return
        self.flush()
        if self._tokens([element]) <= self.max_tokens:
            self.pending.append(element)
            return
        for number, piece in enumerate(self._pieces(element.text or "")):
            key = f"text:{element.id}:{number}"
            self._emit(UnitType.TEXT, key, piece, (element,))

    def _pieces(self, text: str) -> Iterator[str]:
        piece: list[str] = []
        for sentence in split_sentences(text):
            candidate = " ".join([*piece, sentence])
            if piece and self._count(candidate) > self.max_tokens:
                yield " ".join(piece)
                piece = []
            piece.append(sentence)
        if piece:
            yield " ".join(piece)

    def _table(self, head: ExtractedElement) -> None:
        parts = [head]
        while (following := self.links.next_part.get(parts[-1].id)) is not None:
            parts.append(self.elements[following])
        titles = [self.elements[c] for part in parts for c in self._captions(part)]
        texts = [title.text or "" for title in titles]
        for part in parts:
            texts.append(_part_markdown(head, part))
        members = tuple(sorted([*titles, *parts], key=lambda e: e.reading_order))
        self._emit(UnitType.TABLE, f"table:{head.id}", "\n".join(texts), members)

    def _figure(self, image: ExtractedElement) -> None:
        captions = [self.elements[c] for c in self._captions(image)]
        texts = [caption.text or "" for caption in captions]
        texts += [" ".join(image.labels), image.description or ""]
        text = "\n".join(t for t in texts if t)
        if text:
            members = tuple(sorted([image, *captions], key=lambda e: e.reading_order))
            key = f"figure:{image.id}"
            self._emit(UnitType.FIGURE, key, text, members, image_key=image.image_key)

    def _captions(self, element: ExtractedElement) -> tuple[uuid.UUID, ...]:
        return self.links.captions.get(element.id, ())

    def _emit(
        self,
        unit_type: UnitType,
        key: str,
        text: str,
        members: Sequence[ExtractedElement],
        *,
        image_key: str | None = None,
    ) -> None:
        figures = dict.fromkeys(
            figure_id
            for member in members
            for figure_id in self.links.near.get(member.id, ())
            if not self.elements[figure_id].is_decorative
        )
        self.units.append(
            RetrievalUnit(
                id=unit_id_for(document_sha256=self.sha256, unit_key=key),
                document_id=self.document_id,
                unit_type=unit_type,
                text=text,
                heading_path=self.path,
                pages=tuple(sorted({member.page for member in members})),
                element_ids=tuple(member.id for member in members),
                boxes=tuple(PagedBox(page=m.page, bbox=m.bbox) for m in members),
                figure_ids=tuple(figures),
                image_key=image_key,
            )
        )

    def _tokens(self, members: Sequence[ExtractedElement]) -> int:
        return self._count("\n".join(member.text or "" for member in members))

    def _count(self, text: str) -> int:
        return self.counter.count("\n".join((*self.path, text)))


def _part_markdown(head: ExtractedElement, part: ExtractedElement) -> str:
    text = part.text or ""
    if part is head or not repeats_header(head, part):
        return text
    # Drops the repeated header and its separator line before joining the parts.
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _HEADER_SEPARATOR.match(line):
            return "\n".join(lines[index + 1 :])
    return text
