"""Builders of domain elements for tests of the ingestion rules."""

import uuid
from typing import Any

from multimodal_rag.ingestion.domain import (
    BoundingBox,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PageSize,
    RelationshipKind,
    element_id_for,
)

DOCUMENT_ID = uuid.UUID("6f1d2b1e-0000-4000-8000-000000000001")
SHA = "d" * 64
LETTER = PageSize(width=612, height=792)
FULL_WIDTH = (72.0, 540.0)

_TEXT_KINDS = {
    ElementKind.HEADING,
    ElementKind.PARAGRAPH,
    ElementKind.LIST_ITEM,
    ElementKind.CAPTION,
    ElementKind.PAGE_FURNITURE,
}


def make(
    order: int,
    kind: ElementKind = ElementKind.PARAGRAPH,
    *,
    page: int = 1,
    top: float = 100,
    bottom: float = 120,
    columns: tuple[float, float] = FULL_WIDTH,
    **values: Any,
) -> ExtractedElement:
    """Build an element at a reading position, with text for text kinds."""
    fields: dict[str, Any] = {
        "id": element_id_for(document_sha256=SHA, element_key=str(order)),
        "document_id": DOCUMENT_ID,
        "kind": kind,
        "page": page,
        "bbox": BoundingBox(left=columns[0], top=top, right=columns[1], bottom=bottom),
        "reading_order": order,
    }
    if kind in _TEXT_KINDS:
        fields["text"] = f"text {order}"
    if kind is ElementKind.HEADING:
        fields["heading_level"] = 1
    if kind is ElementKind.TABLE:
        rows = (("Part", "Code"), (f"row {order}", "A-1"))
        fields["table"] = rows
        fields["text"] = markdown(rows)
    return ExtractedElement(**(fields | values))


def markdown(rows: tuple[tuple[str, ...], ...]) -> str:
    """Render rows as a Markdown table with a header separator, like Docling."""
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    separator = "|" + "|".join("---" for _ in rows[0]) + "|"
    return "\n".join([lines[0], separator, *lines[1:]])


def link(
    source: ExtractedElement,
    target: ExtractedElement,
    kind: RelationshipKind,
    score: float | None = None,
) -> ElementRelationship:
    """Build a relationship between two elements."""
    return ElementRelationship(
        source_id=source.id, target_id=target.id, kind=kind, score=score
    )
