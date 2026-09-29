from collections.abc import Sequence

from multimodal_rag.ingestion.domain import (
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PagedBox,
    RelationshipKind,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.ingestion.retrieval_units import build_units
from tests.builders import DOCUMENT_ID, SHA, link, make, markdown
from tests.fakes import WordTokenCounter

HEADING = ElementKind.HEADING
TABLE = ElementKind.TABLE
IMAGE = ElementKind.IMAGE


def units(
    elements: Sequence[ExtractedElement],
    relationships: Sequence[ElementRelationship] = (),
    *,
    max_tokens: int = 100,
) -> tuple[RetrievalUnit, ...]:
    return build_units(
        document_id=DOCUMENT_ID,
        document_sha256=SHA,
        elements=elements,
        relationships=relationships,
        counter=WordTokenCounter(),
        max_tokens=max_tokens,
    )


def words(order: int, count: int, **values: object) -> ExtractedElement:
    text = " ".join(f"w{order}_{n}" for n in range(count))
    return make(order, text=text, **values)  # type: ignore[arg-type]


def heading(order: int, text: str, level: int = 1) -> ExtractedElement:
    return make(order, HEADING, text=text, heading_level=level)


def orders(unit: RetrievalUnit, elements: Sequence[ExtractedElement]) -> list[int]:
    position = {element.id: element.reading_order for element in elements}
    return [position[element_id] for element_id in unit.element_ids]


class TestTextUnits:
    def test_headings_start_new_units_and_become_their_path(self) -> None:
        elements = [
            heading(0, "Intro"),
            words(1, 3),
            words(2, 3),
            heading(3, "Setup"),
            words(4, 3),
        ]

        result = units(elements)

        assert [orders(u, elements) for u in result] == [[1, 2], [4]]
        assert [u.heading_path for u in result] == [("Intro",), ("Setup",)]
        assert result[0].text == f"{elements[1].text}\n{elements[2].text}"
        assert result[0].unit_type is UnitType.TEXT

    def test_the_path_follows_levels_even_when_levels_are_skipped(self) -> None:
        elements = [
            heading(0, "Chapter 4", level=1),
            heading(1, "Magneto", level=4),
            words(2, 2),
            heading(3, "Coil", level=4),
            words(4, 2),
            heading(5, "Generators", level=1),
            words(6, 2),
        ]

        paths = [u.heading_path for u in units(elements)]

        assert paths == [
            ("Chapter 4", "Magneto"),
            ("Chapter 4", "Coil"),
            ("Generators",),
        ]

    def test_paragraphs_merge_up_to_the_ceiling_counted_with_the_path(
        self,
    ) -> None:
        elements = [heading(0, "Intro"), words(1, 4), words(2, 4), words(3, 4)]

        result = units(elements, max_tokens=9)

        assert [orders(u, elements) for u in result] == [[1, 2], [3]]
        assert result[0].embedding_text == f"Intro\n{result[0].text}"

    def test_an_oversize_paragraph_splits_only_at_sentence_ends(self) -> None:
        paragraph = make(
            0, text="One two three. Four five six? Seven eight nine ten eleven twelve!"
        )

        result = units([paragraph], max_tokens=7)

        assert [u.text for u in result] == [
            "One two three. Four five six?",
            "Seven eight nine ten eleven twelve!",
        ]
        assert all(u.element_ids == (paragraph.id,) for u in result)
        assert len({u.id for u in result}) == 2

    def test_a_sentence_longer_than_the_ceiling_stays_whole(self) -> None:
        paragraph = make(0, text="A very long sentence with far too many words.")

        [unit] = units([paragraph], max_tokens=3)

        assert unit.text == paragraph.text

    def test_page_furniture_and_decorative_images_are_left_out(self) -> None:
        elements = [
            words(0, 2),
            make(1, ElementKind.PAGE_FURNITURE),
            make(2, IMAGE, is_decorative=True, labels=("LOGO",)),
            words(3, 2),
        ]

        [unit] = units(elements)

        assert orders(unit, elements) == [0, 3]

    def test_units_cite_every_page_and_box_and_their_nearby_figures(self) -> None:
        drawing = make(2, IMAGE, page=2, top=300, bottom=500)
        logo = make(3, IMAGE, page=2, is_decorative=True)
        first = words(0, 2, page=1)
        second = words(1, 2, page=2)
        relationships = [
            link(second, drawing, RelationshipKind.NEAR),
            link(first, logo, RelationshipKind.NEAR),
        ]

        text_unit = units([first, second, drawing, logo], relationships)[0]

        assert text_unit.pages == (1, 2)
        assert text_unit.boxes == (
            PagedBox(page=1, bbox=first.bbox),
            PagedBox(page=2, bbox=second.bbox),
        )
        assert text_unit.figure_ids == (drawing.id,)

    def test_a_caption_that_belongs_to_nothing_is_text(self) -> None:
        caption = make(0, ElementKind.CAPTION, text="Note: see chapter 5.")

        [unit] = units([caption])

        assert unit.text == "Note: see chapter 5."


class TestTableUnits:
    def test_a_table_is_one_unit_whatever_its_size(self) -> None:
        rows = tuple((f"part {n}", f"P-{n}") for n in range(40))
        elements = [words(0, 2), make(1, TABLE, table=rows, text=markdown(rows))]

        result = units(elements, max_tokens=10)

        assert [u.unit_type for u in result] == [UnitType.TEXT, UnitType.TABLE]
        assert result[1].text == markdown(rows)

    def test_a_chain_is_one_unit_that_drops_the_repeated_header(self) -> None:
        head_rows = (("Part", "Code"), ("Spark plug", "SP-1"))
        tail_rows = (("Part", "Code"), ("Magneto", "MG-2"))
        title = make(0, ElementKind.CAPTION, text="Table 1. Parts")
        head = make(1, TABLE, table=head_rows, text=markdown(head_rows))
        tail = make(2, TABLE, page=2, table=tail_rows, text=markdown(tail_rows))
        relationships = [
            link(title, head, RelationshipKind.TITLE_OF),
            link(tail, head, RelationshipKind.CONTINUES),
        ]

        [unit] = units([title, head, tail], relationships)

        assert unit.unit_type is UnitType.TABLE
        assert unit.pages == (1, 2)
        assert orders(unit, [title, head, tail]) == [0, 1, 2]
        assert unit.text == "\n".join(
            ["Table 1. Parts", markdown(head_rows), "| Magneto | MG-2 |"]
        )

    def test_a_part_with_its_own_header_row_keeps_it(self) -> None:
        head_rows = (("Part", "Code"), ("Spark plug", "SP-1"))
        tail_rows = (("Magneto", "MG-2"), ("Coil", "CL-3"))
        head = make(0, TABLE, table=head_rows, text=markdown(head_rows))
        tail = make(1, TABLE, page=2, table=tail_rows, text=markdown(tail_rows))

        [unit] = units([head, tail], [link(tail, head, RelationshipKind.CONTINUES)])

        assert unit.text == f"{markdown(head_rows)}\n{markdown(tail_rows)}"

    def test_a_repeated_header_without_a_separator_line_is_kept(self) -> None:
        rows = (("Part", "Code"), ("Magneto", "MG-2"))
        head = make(0, TABLE, table=rows, text=markdown(rows))
        plain = "Part Code\nMagneto MG-2"
        tail = make(1, TABLE, page=2, table=rows, text=plain)

        [unit] = units([head, tail], [link(tail, head, RelationshipKind.CONTINUES)])

        assert unit.text == f"{markdown(rows)}\n{plain}"


class TestFigureUnits:
    def test_a_figure_unit_joins_caption_labels_and_description(self) -> None:
        caption = make(2, ElementKind.CAPTION, text="Figure 1. Magneto circuit")
        drawing = make(
            1,
            IMAGE,
            labels=("V-12", "P-1"),
            image_key="figures/x/y.png",
            description="A magneto wired to valve V-12.",
        )
        relationships = [link(caption, drawing, RelationshipKind.CAPTION_OF)]

        [unit] = units([heading(0, "Ignition"), drawing, caption], relationships)

        assert unit.unit_type is UnitType.FIGURE
        assert unit.text == (
            "Figure 1. Magneto circuit\nV-12 P-1\nA magneto wired to valve V-12."
        )
        assert unit.image_key == "figures/x/y.png"
        assert unit.heading_path == ("Ignition",)
        assert set(unit.element_ids) == {drawing.id, caption.id}

    def test_a_figure_with_nothing_to_say_has_no_unit(self) -> None:
        assert units([make(0, IMAGE)]) == ()

    def test_a_figure_breaks_the_surrounding_text(self) -> None:
        elements = [words(0, 2), make(1, IMAGE, labels=("V-12",)), words(2, 2)]

        result = units(elements)

        assert [u.unit_type for u in result] == [
            UnitType.TEXT,
            UnitType.FIGURE,
            UnitType.TEXT,
        ]


def test_unit_ids_are_stable_across_runs_and_distinct() -> None:
    elements = [heading(0, "Intro"), words(1, 2), make(2, IMAGE, labels=("A-1",))]

    first, second = units(elements), units(elements)

    assert [u.id for u in first] == [u.id for u in second]
    assert len({u.id for u in first}) == len(first) == 2
