"""Translation of a Docling document into domain elements.

Docling nests the text it finds inside a figure or a table cell under that item, at any
depth, for example inside a list group. Such text belongs to its figure, as labels, or
to its table, and never becomes running text. Only the captions and footnotes of a
figure or table are elements of their own.

Docling's reading order model assigns captions to figures and tables, sometimes a text
its layout model labeled as body text. Every text a figure or table references as a
caption becomes a caption element, linked to its figure (``caption_of``) or its table
(``title_of``).
"""

import io
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from docling_core.types.doc import (
    ContentLayer,
    DocItem,
    DocItemLabel,
    DoclingDocument,
    FloatingItem,
    NodeItem,
    PictureItem,
    ProvenanceItem,
    TableItem,
    TextItem,
)

from multimodal_rag.adapters.docling.headings import HeadingLevels
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PageSize,
    RelationshipKind,
    TextOrigin,
    element_id_for,
)

_KIND_BY_LABEL = {
    DocItemLabel.TITLE: ElementKind.HEADING,
    DocItemLabel.SECTION_HEADER: ElementKind.HEADING,
    DocItemLabel.CAPTION: ElementKind.CAPTION,
    DocItemLabel.LIST_ITEM: ElementKind.LIST_ITEM,
    DocItemLabel.PAGE_HEADER: ElementKind.PAGE_FURNITURE,
    DocItemLabel.PAGE_FOOTER: ElementKind.PAGE_FURNITURE,
}
LAYERS = {ContentLayer.BODY, ContentLayer.FURNITURE}


@dataclass(frozen=True, slots=True)
class DocumentContext:
    """Facts about the whole document that every batch needs.

    Attributes:
        document_id: Document the elements belong to.
        sha256: Fingerprint used to derive stable element ids.
        pages_without_text: 1-based pages whose text came from recognition.
        headings: Resolver of heading levels for the whole document.
    """

    document_id: uuid.UUID
    sha256: str
    pages_without_text: frozenset[int]
    headings: HeadingLevels


@dataclass(frozen=True, slots=True)
class MappedBatch:
    """Elements of one converted page range.

    Attributes:
        elements: Elements in reading order.
        images: PNG bytes of each image element, keyed by element id.
        relationships: Caption links Docling assigned within the range.
        page_sizes: Size of each converted page.
    """

    elements: tuple[ExtractedElement, ...]
    images: dict[uuid.UUID, bytes]
    relationships: tuple[ElementRelationship, ...]
    page_sizes: dict[int, PageSize]


def map_document(
    document: DoclingDocument,
    *,
    context: DocumentContext,
    first_order: int,
    ocr_scores: Mapping[int, float | None],
) -> MappedBatch:
    """Translate the items of a Docling document into domain elements.

    Args:
        document: Result of converting one page range.
        context: Facts about the whole document.
        first_order: Reading order of the first element, continuing earlier batches.
        ocr_scores: Mean recognition confidence per 1-based page, when known.

    Returns:
        The elements, the crops of their images, their caption links and the
        size of each page.

    Raises:
        InvalidBoundingBoxError: If an item lies outside its page.
    """
    mapper = _Mapper(document, context, ocr_scores)
    elements: list[ExtractedElement] = []
    ids_by_ref: dict[str, list[uuid.UUID]] = {}
    floating: list[tuple[ExtractedElement, FloatingItem]] = []
    for item, _ in document.iterate_items(
        included_content_layers=LAYERS, traverse_pictures=True
    ):
        if not (isinstance(item, DocItem) and item.prov and mapper.is_element(item)):
            continue
        if isinstance(item, TextItem):
            # A paragraph that continues on the next page becomes one element per
            # page, so every element keeps a single page and position.
            for provenance, text in _fragments(item):
                order = first_order + len(elements)
                element = mapper.text(item, provenance, text, order=order)
                ids_by_ref.setdefault(item.self_ref, []).append(element.id)
                elements.append(element)
        elif isinstance(item, PictureItem | TableItem):
            element = mapper.floating(item, order=first_order + len(elements))
            floating.append((element, item))
            elements.append(element)
    return MappedBatch(
        elements=tuple(elements),
        images=mapper.images,
        relationships=_caption_links(floating, ids_by_ref),
        page_sizes={
            number: PageSize(width=page.size.width, height=page.size.height)
            for number, page in document.pages.items()
        },
    )


def _caption_links(
    floating: list[tuple[ExtractedElement, FloatingItem]],
    ids_by_ref: dict[str, list[uuid.UUID]],
) -> tuple[ElementRelationship, ...]:
    links = []
    for element, item in floating:
        kind = (
            RelationshipKind.CAPTION_OF
            if element.kind is ElementKind.IMAGE
            else RelationshipKind.TITLE_OF
        )
        for ref in item.captions:
            links += [
                ElementRelationship(source_id=caption, target_id=element.id, kind=kind)
                for caption in ids_by_ref.get(ref.cref, [])
            ]
    return tuple(links)


class _Mapper:
    def __init__(
        self,
        document: DoclingDocument,
        context: DocumentContext,
        ocr_scores: Mapping[int, float | None],
    ) -> None:
        self._doc = document
        self._context = context
        self._ocr_scores = ocr_scores
        self.images: dict[uuid.UUID, bytes] = {}
        self._captions = {
            ref.cref
            for item, _ in document.iterate_items(
                included_content_layers=LAYERS, traverse_pictures=True
            )
            if isinstance(item, FloatingItem)
            for ref in item.captions
        }

    def is_element(self, item: DocItem) -> bool:
        if not isinstance(item, TextItem | TableItem | PictureItem):
            return False
        owner = self._owner(item)
        if owner is None:
            return True
        if isinstance(item, TextItem):
            return _is_attached_text(item, owner)
        # A figure in a table stays a figure. Anything in a figure is part of it.
        return isinstance(owner, TableItem) and isinstance(item, PictureItem)

    def text(
        self, item: TextItem, provenance: ProvenanceItem, text: str, *, order: int
    ) -> ExtractedElement:
        kind = _KIND_BY_LABEL.get(item.label, ElementKind.PARAGRAPH)
        if item.self_ref in self._captions:
            kind = ElementKind.CAPTION
        level = None
        if kind is ElementKind.HEADING:
            level = self._context.headings.level_of(text, page=provenance.page_no)
        return self._build(provenance, order, kind=kind, text=text, heading_level=level)

    def floating(
        self, item: PictureItem | TableItem, *, order: int
    ) -> ExtractedElement:
        if isinstance(item, PictureItem):
            return self._image(item, order)
        return self._build(
            item.prov[0],
            order,
            kind=ElementKind.TABLE,
            text=item.export_to_markdown(self._doc),
            table=tuple(tuple(cell.text for cell in row) for row in item.data.grid),
        )

    def _owner(self, item: DocItem) -> PictureItem | TableItem | None:
        # Nearest figure or table among the ancestors, at any depth.
        node: NodeItem | None = item.parent.resolve(self._doc) if item.parent else None
        while node is not None:
            if isinstance(node, PictureItem | TableItem):
                return node
            node = node.parent.resolve(self._doc) if node.parent else None
        return None

    def _image(self, item: PictureItem, order: int) -> ExtractedElement:
        image = item.get_image(self._doc)
        if image is not None:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            self.images[self._id(order)] = buffer.getvalue()
        classification = item.meta.classification if item.meta else None
        labels = tuple(
            child.text
            for child, _ in self._doc.iterate_items(
                root=item, traverse_pictures=True, included_content_layers=LAYERS
            )
            if isinstance(child, TextItem)
            and not _is_attached_text(child, item)
            and child.text.strip()
        )
        return self._build(
            item.prov[0],
            order,
            kind=ElementKind.IMAGE,
            image_class=(
                classification.predictions[0].class_name
                if classification and classification.predictions
                else None
            ),
            labels=labels,
        )

    def _id(self, order: int) -> uuid.UUID:
        return element_id_for(
            document_sha256=self._context.sha256, element_key=str(order)
        )

    def _build(
        self,
        provenance: ProvenanceItem,
        order: int,
        *,
        kind: ElementKind,
        text: str | None = None,
        heading_level: int | None = None,
        table: tuple[tuple[str, ...], ...] | None = None,
        image_class: str | None = None,
        labels: tuple[str, ...] = (),
    ) -> ExtractedElement:
        page = provenance.page_no
        # Images keep the text-layer origin, their labels carry no confidence.
        recognized = (
            kind is not ElementKind.IMAGE and page in self._context.pages_without_text
        )
        return ExtractedElement(
            id=self._id(order),
            document_id=self._context.document_id,
            kind=kind,
            page=page,
            bbox=self._box(provenance),
            reading_order=order,
            origin=TextOrigin.RECOGNIZED if recognized else TextOrigin.TEXT_LAYER,
            confidence=self._ocr_score(page) if recognized else None,
            heading_level=heading_level,
            text=text,
            table=table,
            image_class=image_class,
            labels=labels,
        )

    def _box(self, provenance: ProvenanceItem) -> BoundingBox:
        size = self._doc.pages[provenance.page_no].size
        box = provenance.bbox.to_top_left_origin(page_height=size.height)
        return BoundingBox.on_page(
            left=box.l,
            top=box.t,
            right=box.r,
            bottom=box.b,
            page_width=size.width,
            page_height=size.height,
        )

    def _ocr_score(self, page: int) -> float | None:
        score = self._ocr_scores.get(page)
        return score if score is not None and math.isfinite(score) else None


def _fragments(item: TextItem) -> list[tuple[ProvenanceItem, str]]:
    """Split the text of an item that Docling merged from several fragments.

    Docling records each fragment's position and character span. It joins fragments
    with a space, or drops the trailing hyphen of a word cut across pages, while the
    recorded span always assumes the space. Spans that do not fit the text keep the
    whole text on the first fragment.
    """
    text = item.text
    starts = [provenance.charspan[0] for provenance in item.prov]
    if len(starts) == 1 or starts[0] != 0 or starts != sorted(set(starts)):
        return [(item.prov[0], text)]
    if starts[-1] > len(text) + 1:
        return [(item.prov[0], text)]
    pieces = []
    begin = 0
    for provenance, start in zip(item.prov, [*starts[1:], None], strict=True):
        if start is None:
            end = following = len(text)
        elif text[start - 1 : start] == " ":
            end, following = start - 1, start
        else:
            end = following = max(begin, start - 2)
        pieces.append((provenance, text[begin:end].strip()))
        begin = following
    return [(provenance, piece) for provenance, piece in pieces if piece] or [
        (item.prov[0], text)
    ]


def _is_attached_text(item: TextItem, owner: FloatingItem) -> bool:
    """Whether a text is the caption or a footnote of its figure or table."""
    attached = {ref.cref for ref in (*owner.captions, *owner.footnotes)}
    return item.self_ref in attached or item.label is DocItemLabel.CAPTION
