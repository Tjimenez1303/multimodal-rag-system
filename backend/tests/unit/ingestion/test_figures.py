import uuid
from collections.abc import Mapping, Sequence

import pytest

from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    ExtractedElement,
    RelationshipKind,
)
from multimodal_rag.ingestion.figures import (
    DescriptionContext,
    FigurePolicy,
    FigureTriage,
    description_context,
    unverified_identifiers,
)
from multimodal_rag.shared.errors import DataInconsistencyError
from tests.builders import LETTER, link, make

IMAGE = ElementKind.IMAGE
POLICY = FigurePolicy(decorative_min_pages=3, decorative_min_page_share=0.2)


def figure(order: int, *, page: int = 1, **values: object) -> ExtractedElement:
    """A 468 x 200 pt drawing, 19% of a letter page."""
    fields = {"top": 100, "bottom": 300, "image_class": "engineering_drawing"}
    return make(order, IMAGE, page=page, **(fields | values))  # type: ignore[arg-type]


def triage(
    elements: Sequence[ExtractedElement],
    *,
    hashes: Mapping[uuid.UUID, str] | None = None,
    pages_total: int = 10,
    describe: bool = True,
) -> FigureTriage:
    known = hashes if hashes is not None else {e.id: str(e.id) for e in elements}
    return POLICY.triage(
        elements,
        image_hashes=known,
        page_sizes=dict.fromkeys(range(1, pages_total + 1), LETTER),
        pages_total=pages_total,
        describe=describe,
    )


def by_order(result: FigureTriage) -> dict[int, ExtractedElement]:
    return {element.reading_order: element for element in result.elements}


@pytest.mark.parametrize(
    "image_class",
    [
        "logo",
        "icon",
        "signature",
        "stamp",
        "bar_code",
        "qr_code",
        "full_page_image",
        "page_thumbnail",
    ],
)
def test_decorative_classes_are_flagged_and_skipped(image_class: str) -> None:
    result = triage([figure(0, image_class=image_class)])

    [image] = result.elements
    assert image.is_decorative
    assert image.description_status is DescriptionStatus.SKIPPED
    assert result.to_describe == ()


def test_a_relevant_drawing_is_sent_for_description() -> None:
    drawing = figure(0)

    result = triage([drawing, make(1)])

    assert result.to_describe == (drawing.id,)
    assert result.elements == (drawing, make(1))


def test_a_figure_below_five_percent_of_its_page_is_skipped_but_relevant() -> None:
    small = figure(0, top=100, bottom=150, columns=(72.0, 300.0))

    [image] = triage([small]).elements

    assert image.description_status is DescriptionStatus.SKIPPED
    assert not image.is_decorative


@pytest.mark.parametrize(
    ("pages", "pages_total", "decorative"),
    [
        ((1, 2, 3), 50, True),
        ((1, 2), 10, True),
        ((1, 2), 20, False),
        ((1,), 1, False),
    ],
    ids=["three pages", "20% of pages", "under both limits", "single image"],
)
def test_an_image_repeated_across_pages_is_decorative(
    pages: tuple[int, ...], pages_total: int, decorative: bool
) -> None:
    copies = [figure(order, page=page) for order, page in enumerate(pages)]

    result = triage(
        copies,
        hashes={copy.id: "same-bytes" for copy in copies},
        pages_total=pages_total,
    )

    assert [e.is_decorative for e in result.elements] == [decorative] * len(pages)


def test_disabled_descriptions_skip_every_figure() -> None:
    result = triage([figure(0), figure(1, page=2)], describe=False)

    assert result.to_describe == ()
    assert {e.description_status for e in result.elements} == {
        DescriptionStatus.SKIPPED
    }


def test_a_figure_without_a_stored_crop_is_skipped() -> None:
    [image] = triage([figure(0)], hashes={}).elements

    assert image.description_status is DescriptionStatus.SKIPPED


def test_identifiers_missing_from_labels_and_caption_are_unverified() -> None:
    description = (
        "Valve V-12 feeds pump P-7 and part 5-3431-201-10 at 1,400 rpm on a 12v "
        "circuit. The v-12 valve closes. Figure 4-2 shows it."
    )

    result = unverified_identifiers(
        description, labels=("v-12", "MAGNETO"), caption="Figure 4-2. Pump P-1"
    )

    assert result == ("P-7", "5-3431-201-10", "12v")


def test_a_description_without_identifiers_has_nothing_unverified() -> None:
    assert unverified_identifiers("A plain drawing.", labels=(), caption=None) == ()


def test_the_description_context_holds_the_caption_and_the_nearby_text() -> None:
    image = figure(0)
    caption = make(1, ElementKind.CAPTION, text="Figure 1. Magneto")
    first = make(2, text="The magneto fires the plugs.")
    second = make(3, text="Check the points.")
    other = make(4, text="Unrelated.")
    relationships = [
        link(caption, image, RelationshipKind.CAPTION_OF),
        link(second, image, RelationshipKind.NEAR),
        link(first, image, RelationshipKind.NEAR),
        link(other, figure(9), RelationshipKind.NEAR),
    ]

    context = description_context(
        image,
        elements={e.id: e for e in (image, caption, first, second, other)},
        relationships=relationships,
    )

    assert context == DescriptionContext(
        caption="Figure 1. Magneto",
        context="The magneto fires the plugs.\nCheck the points.",
    )


def test_a_figure_without_links_has_no_context() -> None:
    image = figure(0)

    context = description_context(image, elements={image.id: image}, relationships=[])

    assert context == DescriptionContext(caption=None, context=None)


def test_a_figure_on_a_page_of_unknown_size_is_an_inconsistency() -> None:
    image = figure(0, page=4)

    with pytest.raises(DataInconsistencyError):
        POLICY.triage(
            [image],
            image_hashes={image.id: "bytes"},
            page_sizes={1: LETTER},
            pages_total=4,
            describe=True,
        )
