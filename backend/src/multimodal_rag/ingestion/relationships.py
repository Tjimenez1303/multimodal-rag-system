"""Links between extracted elements: captions, nearby text and continued tables.

The extractor already reports the captions its layout model assigned. These rules link
the captions it left alone, the text closest to each figure and the parts of a table
that continues on the next page. Distances are in PDF points on top-left boxes.
"""

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence

from multimodal_rag.ingestion.domain import (
    BoundingBox,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PageSize,
    RelationshipKind,
)

_NEAR_KINDS = frozenset({ElementKind.PARAGRAPH, ElementKind.LIST_ITEM})
_CAPTIONED_KINDS = {
    ElementKind.IMAGE: RelationshipKind.CAPTION_OF,
    ElementKind.TABLE: RelationshipKind.TITLE_OF,
}
_CAPTION_LINKS = frozenset(_CAPTIONED_KINDS.values())
# Marks a caption as the continuation of a table: continued, cont., continuación or
# continúa.
_CONTINUED = re.compile(r"\bcont(?:inu|\.)", re.IGNORECASE)
CONTINUED_SCORE = 1.0
CONTINUES_SCORE = 0.9


def link_elements(
    elements: Sequence[ExtractedElement],
    *,
    page_sizes: Mapping[int, PageSize],
    extracted: Sequence[ElementRelationship],
    near_max_points: float,
) -> tuple[ElementRelationship, ...]:
    """Compute every relationship between the elements of a document.

    Args:
        elements: Elements of the whole document.
        page_sizes: Size of every page that holds an element.
        extracted: Caption links reported by the extractor, which are kept.
        near_max_points: Largest gap between a figure or caption and nearby text.

    Returns:
        The extracted links followed by the computed ones, without duplicates.

    Raises:
        UnknownPageSizeError: If a table lies on a page of unknown size.
    """
    ordered = sorted(elements, key=lambda element: element.reading_order)
    links = list(dict.fromkeys(extracted))
    links += _caption_fallback(ordered, links, near_max_points)
    links += _near(ordered, links, near_max_points)
    links += _continuations(ordered, links, page_sizes)
    return tuple(links)


def repeats_header(head: ExtractedElement, part: ExtractedElement) -> bool:
    """Tell whether a table part starts by repeating the header row of its head.

    Args:
        head: First part of the table.
        part: A later part of the same table.

    Returns:
        Whether both first rows hold the same cells, ignoring case and spacing.
    """
    if not head.table or not part.table:
        return False
    return _normalized_row(head.table[0]) == _normalized_row(part.table[0])


def _caption_fallback(
    elements: Sequence[ExtractedElement],
    links: Sequence[ElementRelationship],
    max_gap: float,
) -> list[ElementRelationship]:
    linked = {link.source_id for link in links if link.kind in _CAPTION_LINKS}
    captioned = {link.target_id for link in links if link.kind in _CAPTION_LINKS}
    found: list[ElementRelationship] = []
    candidates = [e for e in elements if e.kind in _CAPTIONED_KINDS]
    for index, caption in enumerate(elements):
        if caption.kind is not ElementKind.CAPTION or caption.id in linked:
            continue
        free = (e for e in candidates if e.id not in captioned)
        target = _closest(caption, free, max_gap) or _across_break(elements, index)
        if target is None or target.id in captioned:
            continue
        captioned.add(target.id)
        found.append(
            ElementRelationship(
                source_id=caption.id,
                target_id=target.id,
                kind=_CAPTIONED_KINDS[target.kind],
            )
        )
    return found


def _across_break(
    elements: Sequence[ExtractedElement], index: int
) -> ExtractedElement | None:
    # A caption that opens its page belongs to a figure or table closing the last one.
    caption = elements[index]
    before = [e for e in elements[:index] if e.kind is not ElementKind.PAGE_FURNITURE]
    if not before or any(e.page == caption.page for e in before):
        return None
    previous = before[-1]
    if previous.page == caption.page - 1 and previous.kind in _CAPTIONED_KINDS:
        return previous
    return None


def _near(
    elements: Sequence[ExtractedElement],
    links: Sequence[ElementRelationship],
    max_gap: float,
) -> list[ElementRelationship]:
    by_id = {element.id: element for element in elements}
    texts = [element for element in elements if element.kind in _NEAR_KINDS]
    found: list[ElementRelationship] = []
    for image in (e for e in elements if e.kind is ElementKind.IMAGE):
        anchors = [image] + [
            by_id[link.source_id]
            for link in links
            if link.kind is RelationshipKind.CAPTION_OF
            and link.target_id == image.id
            and by_id[link.source_id].page == image.page + 1
        ]
        scored = [
            (gap, text)
            for anchor in anchors
            for text in texts
            if (gap := _gap(anchor, text)) is not None and gap <= max_gap
        ]
        if scored:
            gap, text = min(scored, key=lambda pair: (pair[0], pair[1].reading_order))
            found.append(
                ElementRelationship(
                    source_id=text.id,
                    target_id=image.id,
                    kind=RelationshipKind.NEAR,
                    score=1 - gap / max_gap,
                )
            )
    return found


def _continuations(
    elements: Sequence[ExtractedElement],
    links: Sequence[ElementRelationship],
    page_sizes: Mapping[int, PageSize],
) -> list[ElementRelationship]:
    titles = {
        link.source_id: link.target_id
        for link in links
        if link.kind is RelationshipKind.TITLE_OF
    }
    tables = [index for index, e in enumerate(elements) if e.kind is ElementKind.TABLE]
    found: list[ElementRelationship] = []
    for first, second in zip(tables, tables[1:], strict=False):
        earlier, later = elements[first], elements[second]
        between = elements[first + 1 : second]
        if _continues(earlier, later, between, titles, page_sizes):
            continued = any(
                _is_continued(e) for e in between if titles.get(e.id) == later.id
            )
            found.append(
                ElementRelationship(
                    source_id=later.id,
                    target_id=earlier.id,
                    kind=RelationshipKind.CONTINUES,
                    score=CONTINUED_SCORE if continued else CONTINUES_SCORE,
                )
            )
    return found


def _continues(
    earlier: ExtractedElement,
    later: ExtractedElement,
    between: Iterable[ExtractedElement],
    titles: Mapping[uuid.UUID, uuid.UUID],
    page_sizes: Mapping[int, PageSize],
) -> bool:
    if later.page != earlier.page + 1 or _columns(earlier) != _columns(later):
        return False
    if not _columns(earlier):
        return False
    interrupted = any(
        element.kind not in (ElementKind.PAGE_FURNITURE, ElementKind.IMAGE)
        and titles.get(element.id) not in (earlier.id, later.id)
        for element in between
    )
    return (
        not interrupted
        and earlier.bbox.bottom > PageSize.of_page(page_sizes, earlier.page).height / 2
        and later.bbox.top < PageSize.of_page(page_sizes, later.page).height / 2
    )


def _closest(
    caption: ExtractedElement, candidates: Iterable[ExtractedElement], max_gap: float
) -> ExtractedElement | None:
    scored = [
        (gap, candidate)
        for candidate in candidates
        if (gap := _gap(caption, candidate)) is not None and gap <= max_gap
    ]
    if not scored:
        return None
    return min(scored, key=lambda pair: (pair[0], pair[1].reading_order))[1]


def _gap(first: ExtractedElement, second: ExtractedElement) -> float | None:
    """Vertical gap between two elements of one page and one column, else ``None``."""
    if first.page != second.page or not _overlap(first.bbox, second.bbox):
        return None
    return max(
        0.0,
        max(first.bbox.top, second.bbox.top)
        - min(first.bbox.bottom, second.bbox.bottom),
    )


def _overlap(first: BoundingBox, second: BoundingBox) -> bool:
    return min(first.right, second.right) > max(first.left, second.left)


def _columns(table: ExtractedElement) -> int:
    return len(table.table[0]) if table.table else 0


def _is_continued(caption: ExtractedElement) -> bool:
    return _CONTINUED.search(caption.text or "") is not None


def _normalized_row(row: Sequence[str]) -> tuple[str, ...]:
    return tuple(" ".join(cell.casefold().split()) for cell in row)
