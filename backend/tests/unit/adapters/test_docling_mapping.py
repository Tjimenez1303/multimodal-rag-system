import uuid

import pytest
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    GroupLabel,
    ProvenanceItem,
    Size,
    TableData,
)

from multimodal_rag.adapters.docling.headings import HeadingLevels
from multimodal_rag.adapters.docling.mapping import (
    DocumentContext,
    MappedBatch,
    map_document,
)
from multimodal_rag.ingestion.domain import (
    ElementKind,
    ExtractedElement,
    PageSize,
    RelationshipKind,
    TextOrigin,
)

PAGE = Size(width=612, height=792)


def provenance(top: float = 700, bottom: float = 650) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=1,
        charspan=(0, 1),
        bbox=BoundingBox(
            l=72, t=top, r=300, b=bottom, coord_origin=CoordOrigin.BOTTOMLEFT
        ),
    )


def context(*, recognized: frozenset[int] = frozenset()) -> DocumentContext:
    return DocumentContext(
        document_id=uuid.uuid4(),
        sha256="a" * 64,
        pages_without_text=recognized,
        headings=HeadingLevels([]),
    )


def mapped_batch(
    document: DoclingDocument, *, recognized: frozenset[int] = frozenset()
) -> MappedBatch:
    return map_document(
        document,
        context=context(recognized=recognized),
        first_order=0,
        ocr_scores={1: 0.87},
    )


def mapped(
    document: DoclingDocument, *, recognized: frozenset[int] = frozenset()
) -> list[ExtractedElement]:
    return list(mapped_batch(document, recognized=recognized).elements)


@pytest.fixture
def document() -> DoclingDocument:
    document = DoclingDocument(name="manual")
    document.add_page(page_no=1, size=PAGE)
    return document


def test_text_nested_anywhere_inside_a_figure_becomes_its_labels(
    document: DoclingDocument,
) -> None:
    figure = document.add_picture(prov=provenance())
    # Docling puts recognized list text in a list group under the figure.
    labels = document.add_list_group(parent=figure)
    document.add_list_item(parent=labels, text="V-12 valve", prov=provenance())
    document.add_heading(parent=figure, text="SECTION A-A", prov=provenance())
    caption = document.add_text(
        label=DocItemLabel.CAPTION,
        text="Figure 1. Fuel system",
        parent=figure,
        prov=provenance(),
    )
    figure.captions.append(caption.get_ref())
    document.add_text(label=DocItemLabel.TEXT, text="Body text", prov=provenance())

    elements = mapped(document)

    assert [(e.kind, e.text) for e in elements] == [
        (ElementKind.IMAGE, None),
        (ElementKind.CAPTION, "Figure 1. Fuel system"),
        (ElementKind.PARAGRAPH, "Body text"),
    ]
    assert set(elements[0].labels) == {"V-12 valve", "SECTION A-A"}


def test_text_inside_table_cells_stays_in_the_table(
    document: DoclingDocument,
) -> None:
    table = document.add_table(
        data=TableData(num_rows=1, num_cols=1), prov=provenance()
    )
    cell = document.add_group(
        label=GroupLabel.UNSPECIFIED, name="rich_cell_group_1_0_0", parent=table
    )
    document.add_text(
        label=DocItemLabel.TEXT, text="cell text", prov=provenance(), parent=cell
    )

    elements = mapped(document)

    assert [e.kind for e in elements] == [ElementKind.TABLE]


def test_boxes_are_converted_to_a_top_left_origin(document: DoclingDocument) -> None:
    document.add_text(
        label=DocItemLabel.TEXT, text="Body", prov=provenance(top=700, bottom=650)
    )

    [element] = mapped(document)

    assert (element.bbox.top, element.bbox.bottom) == (92, 142)


def test_text_on_pages_without_a_text_layer_is_recognized(
    document: DoclingDocument,
) -> None:
    document.add_text(label=DocItemLabel.TEXT, text="Scanned", prov=provenance())

    [element] = mapped(document, recognized=frozenset({1}))

    assert element.origin is TextOrigin.RECOGNIZED
    assert element.confidence == 0.87


def test_a_paragraph_continuing_on_the_next_page_becomes_one_element_per_page(
    document: DoclingDocument,
) -> None:
    document.add_page(page_no=2, size=PAGE)
    first, second = "The magneto fires ", "the spark plugs."
    paragraph = document.add_text(
        label=DocItemLabel.TEXT,
        text=first + second,
        prov=ProvenanceItem(
            page_no=1,
            charspan=(0, len(first)),
            bbox=BoundingBox(
                l=72, t=100, r=300, b=60, coord_origin=CoordOrigin.BOTTOMLEFT
            ),
        ),
    )
    paragraph.prov.append(
        ProvenanceItem(
            page_no=2,
            charspan=(len(first), len(first) + len(second)),
            bbox=BoundingBox(
                l=72, t=760, r=300, b=720, coord_origin=CoordOrigin.BOTTOMLEFT
            ),
        )
    )

    elements = mapped(document)

    assert [(e.page, e.text, e.reading_order) for e in elements] == [
        (1, "The magneto fires", 0),
        (2, "the spark plugs.", 1),
    ]
    assert elements[1].bbox.top == 32


def test_a_word_hyphenated_across_pages_is_split_where_docling_joined_it(
    document: DoclingDocument,
) -> None:
    document.add_page(page_no=2, size=PAGE)
    # Docling drops the trailing hyphen when it joins "mag-" and "neto fires".
    first = "The mag"
    paragraph = document.add_text(
        label=DocItemLabel.TEXT,
        text="The magneto fires",
        prov=ProvenanceItem(
            page_no=1,
            charspan=(0, len(first) + 1),
            bbox=BoundingBox(
                l=72, t=100, r=300, b=60, coord_origin=CoordOrigin.BOTTOMLEFT
            ),
        ),
    )
    paragraph.prov.append(
        ProvenanceItem(
            page_no=2,
            charspan=(len(first) + 2, len(first) + 2 + len("neto fires")),
            bbox=BoundingBox(
                l=72, t=760, r=300, b=720, coord_origin=CoordOrigin.BOTTOMLEFT
            ),
        )
    )

    elements = mapped(document)

    assert [(e.page, e.text) for e in elements] == [(1, "The mag"), (2, "neto fires")]


def test_captions_assigned_by_docling_become_caption_and_title_links(
    document: DoclingDocument,
) -> None:
    figure = document.add_picture(prov=provenance())
    figure_caption = document.add_text(
        label=DocItemLabel.CAPTION, text="Figure 1.", parent=figure, prov=provenance()
    )
    figure.captions.append(figure_caption.get_ref())
    table = document.add_table(
        data=TableData(num_rows=1, num_cols=1), prov=provenance()
    )
    # Docling can assign as a caption a text its layout model labeled as body text.
    title = document.add_text(
        label=DocItemLabel.TEXT, text="Table 1 (continued).", prov=provenance()
    )
    table.captions.append(title.get_ref())

    batch = mapped_batch(document)

    by_text = {e.text: e for e in batch.elements}
    image, table_element = batch.elements[0], batch.elements[2]
    title_element = by_text["Table 1 (continued)."]
    assert title_element.kind is ElementKind.CAPTION
    assert {(r.source_id, r.target_id, r.kind) for r in batch.relationships} == {
        (by_text["Figure 1."].id, image.id, RelationshipKind.CAPTION_OF),
        (title_element.id, table_element.id, RelationshipKind.TITLE_OF),
    }


def test_the_size_of_every_page_is_reported(document: DoclingDocument) -> None:
    document.add_page(page_no=2, size=Size(width=842, height=595))

    batch = mapped_batch(document)

    assert batch.page_sizes == {
        1: PageSize(width=612, height=792),
        2: PageSize(width=842, height=595),
    }
