from collections.abc import Sequence
from typing import Any

import pytest

from multimodal_rag.ingestion.domain import (
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    RelationshipKind,
    element_id_for,
)
from multimodal_rag.ingestion.relationships import link_elements, repeats_header
from multimodal_rag.shared.errors import DataInconsistencyError
from tests.builders import LETTER, SHA, link, make

IMAGE = ElementKind.IMAGE
TABLE = ElementKind.TABLE
CAPTION = ElementKind.CAPTION
FURNITURE = ElementKind.PAGE_FURNITURE
SIZES = dict.fromkeys(range(1, 5), LETTER)
LEFT = (72.0, 290.0)
RIGHT = (320.0, 540.0)


def links(
    elements: Sequence[ExtractedElement],
    extracted: Sequence[ElementRelationship] = (),
) -> tuple[ElementRelationship, ...]:
    return link_elements(
        elements, page_sizes=SIZES, extracted=extracted, near_max_points=72
    )


# The builders derive each id from the reading order, so links read as order pairs.
ORDER_BY_ID = {
    element_id_for(document_sha256=SHA, element_key=str(order)): order
    for order in range(100)
}


def document(*elements: ExtractedElement) -> list[ExtractedElement]:
    return list(elements)


def pairs(
    result: Sequence[ElementRelationship], kind: RelationshipKind
) -> set[tuple[int, int]]:
    return {
        (ORDER_BY_ID[r.source_id], ORDER_BY_ID[r.target_id])
        for r in result
        if r.kind is kind
    }


class TestCaptions:
    def test_caption_links_from_the_extractor_are_kept_once(self) -> None:
        figure = make(0, IMAGE, top=100, bottom=300)
        caption = make(1, CAPTION, top=310, bottom=325)
        extracted = [link(caption, figure, RelationshipKind.CAPTION_OF)]

        result = links(document(figure, caption), extracted)

        assert [r for r in result if r.kind is RelationshipKind.CAPTION_OF] == (
            extracted
        )

    def test_a_caption_left_alone_is_linked_to_the_figure_just_above(self) -> None:
        elements = document(
            make(0, IMAGE, top=100, bottom=300),
            make(1, CAPTION, top=310, bottom=325),
        )

        assert pairs(links(elements), RelationshipKind.CAPTION_OF) == {(1, 0)}

    def test_a_caption_left_alone_above_a_table_becomes_its_title(self) -> None:
        elements = document(
            make(0, CAPTION, top=80, bottom=95),
            make(1, TABLE, top=100, bottom=300),
        )

        assert pairs(links(elements), RelationshipKind.TITLE_OF) == {(0, 1)}

    @pytest.mark.parametrize(
        "caption",
        [
            make(1, CAPTION, top=310, bottom=325, columns=RIGHT),
            make(1, CAPTION, top=380, bottom=395, columns=LEFT),
        ],
        ids=["other column", "too far"],
    )
    def test_a_caption_in_another_column_or_too_far_stays_unlinked(
        self, caption: ExtractedElement
    ) -> None:
        figure = make(0, IMAGE, top=100, bottom=300, columns=LEFT)

        assert links(document(figure, caption)) == ()

    def test_a_figure_that_already_has_a_caption_gets_no_second_one(self) -> None:
        figure = make(0, IMAGE, top=100, bottom=300)
        first = make(1, CAPTION, top=310, bottom=325)
        second = make(2, CAPTION, top=330, bottom=345)
        extracted = [link(first, figure, RelationshipKind.CAPTION_OF)]

        result = links(document(figure, first, second), extracted)

        assert pairs(result, RelationshipKind.CAPTION_OF) == {(1, 0)}

    def test_a_caption_at_the_top_of_the_next_page_is_linked_across_the_break(
        self,
    ) -> None:
        elements = document(
            make(0, IMAGE, top=500, bottom=740),
            make(1, FURNITURE, top=760, bottom=775),
            make(2, FURNITURE, page=2, top=20, bottom=35),
            make(3, CAPTION, page=2, top=60, bottom=75),
        )

        assert pairs(links(elements), RelationshipKind.CAPTION_OF) == {(3, 0)}


class TestNear:
    def test_the_closest_paragraph_in_the_same_column_is_near(self) -> None:
        figure = make(0, IMAGE, top=100, bottom=300, columns=LEFT)
        elements = document(
            figure,
            make(1, top=305, bottom=320, columns=RIGHT),
            make(2, top=320, bottom=340, columns=LEFT),
            make(3, top=360, bottom=380, columns=LEFT),
        )

        result = [r for r in links(elements) if r.kind is RelationshipKind.NEAR]

        assert pairs(result, RelationshipKind.NEAR) == {(2, 0)}
        assert result[0].score == pytest.approx(1 - 20 / 72)

    def test_list_items_count_but_headings_and_captions_do_not(self) -> None:
        elements = document(
            make(0, IMAGE, top=100, bottom=300),
            make(1, ElementKind.HEADING, top=302, bottom=310),
            make(2, CAPTION, page=2, top=20, bottom=30),
            make(3, ElementKind.LIST_ITEM, top=340, bottom=360),
        )

        assert pairs(links(elements), RelationshipKind.NEAR) == {(3, 0)}

    def test_text_beyond_the_distance_limit_is_not_near(self) -> None:
        elements = document(
            make(0, IMAGE, top=100, bottom=300),
            make(1, top=373, bottom=390),
        )

        assert pairs(links(elements), RelationshipKind.NEAR) == set()

    def test_text_under_a_caption_that_continues_on_the_next_page_is_near(
        self,
    ) -> None:
        figure = make(0, IMAGE, top=500, bottom=740)
        caption = make(1, CAPTION, page=2, top=60, bottom=75)
        paragraph = make(2, page=2, top=85, bottom=120)
        extracted = [link(caption, figure, RelationshipKind.CAPTION_OF)]

        result = links(document(figure, caption, paragraph), extracted)

        assert pairs(result, RelationshipKind.NEAR) == {(2, 0)}


class TestContinues:
    def split(
        self, *between: ExtractedElement, **second: Any
    ) -> list[ExtractedElement]:
        first = make(0, TABLE, top=500, bottom=740)
        last = make(10, TABLE, **({"page": 2, "top": 60, "bottom": 300} | second))
        return document(first, *between, last)

    def test_a_table_that_resumes_on_the_next_page_continues_the_first(
        self,
    ) -> None:
        elements = self.split(
            make(1, FURNITURE, top=760, bottom=775),
            make(2, IMAGE, top=745, bottom=790, image_class="logo"),
            make(3, FURNITURE, page=2, top=20, bottom=35),
        )

        result = links(elements)

        assert pairs(result, RelationshipKind.CONTINUES) == {(10, 0)}
        assert next(iter(result)).score == pytest.approx(0.9)

    def test_a_continued_caption_between_the_parts_strengthens_the_link(
        self,
    ) -> None:
        continued = make(
            1, CAPTION, page=2, top=40, bottom=55, text="Table 1 (continued)"
        )
        elements = self.split(continued)
        extracted = [link(continued, elements[-1], RelationshipKind.TITLE_OF)]

        result = links(elements, extracted)

        [continuation] = [r for r in result if r.kind is RelationshipKind.CONTINUES]
        assert continuation.score == pytest.approx(1.0)

    @pytest.mark.parametrize(
        ("between", "second"),
        [
            ((make(1, top=745, bottom=760),), {}),
            ((), {"table": (("a", "b", "c"),), "text": "| a | b | c |"}),
            ((), {"page": 3}),
            ((), {"top": 420, "bottom": 600}),
        ],
        ids=["body text between", "column count", "not next page", "not at top"],
    )
    def test_tables_that_do_not_meet_every_condition_stay_apart(
        self, between: tuple[ExtractedElement, ...], second: dict[str, Any]
    ) -> None:
        elements = self.split(*between, **second)

        assert pairs(links(elements), RelationshipKind.CONTINUES) == set()

    def test_a_first_part_in_the_upper_half_does_not_continue(self) -> None:
        elements = document(
            make(0, TABLE, top=100, bottom=390),
            make(1, TABLE, page=2, top=60, bottom=300),
        )

        assert pairs(links(elements), RelationshipKind.CONTINUES) == set()

    def test_a_page_without_a_known_size_is_an_inconsistency(self) -> None:
        orphan = make(0, TABLE, page=5, top=500, bottom=740)
        next_page = make(10, TABLE, page=6, top=60, bottom=300)

        with pytest.raises(DataInconsistencyError):
            link_elements(
                document(orphan, next_page),
                page_sizes={5: LETTER},
                extracted=(),
                near_max_points=72,
            )


class TestRepeatedHeader:
    def test_a_first_row_equal_up_to_case_and_spacing_repeats_the_header(
        self,
    ) -> None:
        head = make(0, TABLE, table=(("Part", "Code"), ("a", "b")))
        part = make(1, TABLE, table=((" part ", "CODE"), ("c", "d")))

        assert repeats_header(head, part)

    @pytest.mark.parametrize(
        "rows", [(("Spark plug", "SP-1"),), None], ids=["data row", "no rows"]
    )
    def test_a_different_or_missing_first_row_does_not(
        self, rows: tuple[tuple[str, ...], ...] | None
    ) -> None:
        head = make(0, TABLE, table=(("Part", "Code"), ("a", "b")))
        part = make(1, TABLE, table=rows)

        assert not repeats_header(head, part)


@pytest.mark.parametrize("text", ["Tabla 3 (continuación)", "Table 3 (cont.)"])
def test_spanish_and_abbreviated_continued_captions_count(text: str) -> None:
    first = make(0, TABLE, top=500, bottom=740)
    caption = make(1, CAPTION, page=2, top=40, bottom=55, text=text)
    second = make(2, TABLE, page=2, top=60, bottom=300)

    result = links(
        document(first, caption, second),
        [link(caption, second, RelationshipKind.TITLE_OF)],
    )

    [continuation] = [r for r in result if r.kind is RelationshipKind.CONTINUES]
    assert continuation.score == pytest.approx(1.0)


def test_tables_without_rows_never_continue() -> None:
    elements = document(
        make(0, TABLE, top=500, bottom=740, table=None),
        make(1, TABLE, page=2, top=60, bottom=300, table=None),
    )

    assert pairs(links(elements), RelationshipKind.CONTINUES) == set()
