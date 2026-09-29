from collections.abc import Sequence
from typing import Any

import pytest

from multimodal_rag.answering.domain import AnswerImage
from multimodal_rag.answering.images import select_images
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    RelationshipKind,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.shared.errors import DataInconsistencyError
from tests.library import document, element, unit

FAA = document("faa-powerplant.pdf")
NAMES = {FAA.id: FAA.file_name}
TEXT_BOX = BoundingBox(left=72, top=100, right=540, bottom=160)


def figure(page: int = 12, *, top: float = 200, **values: Any) -> ExtractedElement:
    fields: dict[str, Any] = {
        "kind": ElementKind.IMAGE,
        "page": page,
        "bbox": BoundingBox(left=72, top=top, right=540, bottom=top + 100),
        "image_key": "figures/crop.png",
    }
    return element(FAA, **(fields | values))


def text_unit(*figures: ExtractedElement, page: int = 12) -> RetrievalUnit:
    paragraph = element(FAA, page=page, bbox=TEXT_BOX)
    return unit(
        FAA, "Text.", members=[paragraph], figure_ids=tuple(f.id for f in figures)
    )


def figure_unit(image: ExtractedElement) -> RetrievalUnit:
    return unit(FAA, "Figure 4-22.", members=[image], unit_type=UnitType.FIGURE)


def select(
    cited: Sequence[RetrievalUnit],
    elements: Sequence[ExtractedElement],
    relationships: Sequence[ElementRelationship] = (),
) -> tuple[AnswerImage | None, tuple[AnswerImage, ...]]:
    return select_images(
        cited,
        elements={e.id: e for e in elements},
        relationships=relationships,
        document_names=NAMES,
    )


def ids(images: Sequence[AnswerImage | None]) -> list[object]:
    return [None if image is None else image.element_id for image in images]


def test_a_cited_figure_unit_brings_its_own_figure_as_primary() -> None:
    image = figure()
    cited = figure_unit(image)

    primary, related = select([cited], [image])

    assert primary == AnswerImage(
        element_id=image.id,
        document_id=FAA.id,
        document_name="faa-powerplant.pdf",
        page=12,
        bbox=image.bbox,
        caption=None,
        unit_id=cited.id,
    )
    assert related == ()


def test_the_figure_closest_to_the_cited_text_on_its_page_wins() -> None:
    far, near = figure(top=600), figure(top=180)
    other_page = figure(page=13, top=100)
    cited = text_unit(far, other_page, near)

    primary, related = select([cited], [far, near, other_page])

    assert ids([primary]) == [near.id]
    assert ids(related) == [far.id, other_page.id]


def test_figures_of_the_better_ranked_cited_unit_come_first() -> None:
    first_figure, second_figure = figure(top=700), figure(top=170)
    better, worse = text_unit(first_figure), text_unit(second_figure)

    primary, related = select([better, worse], [first_figure, second_figure])

    assert ids([primary]) == [first_figure.id]
    assert ids(related) == [second_figure.id]


def test_decorative_figures_and_figures_without_a_crop_are_never_returned() -> None:
    logo = figure(is_decorative=True)
    uncropped = figure(image_key=None)
    cited = text_unit(logo, uncropped)

    primary, related = select([cited], [logo, uncropped])

    assert (primary, related) == (None, ())


def test_a_figure_brought_by_two_units_appears_once() -> None:
    shared, own = figure(top=180), figure(top=500)
    first, second = text_unit(shared), text_unit(shared, own)

    primary, related = select([first, second], [shared, own])

    assert ids([primary]) == [shared.id]
    assert ids(related) == [own.id]


def test_without_figures_in_the_cited_units_there_is_no_image() -> None:
    assert select([text_unit()], []) == (None, ())


def test_the_caption_comes_from_its_caption_of_relationship() -> None:
    image = figure()
    caption = element(FAA, kind=ElementKind.CAPTION, text="Figure 4-22. Shunt wiring")
    near_text = element(FAA)
    links = [
        ElementRelationship(
            source_id=caption.id, target_id=image.id, kind=RelationshipKind.CAPTION_OF
        ),
        ElementRelationship(
            source_id=near_text.id, target_id=image.id, kind=RelationshipKind.NEAR
        ),
    ]

    primary, _ = select([figure_unit(image)], [image, caption, near_text], links)

    assert primary is not None
    assert primary.caption == "Figure 4-22. Shunt wiring"


def test_a_caption_missing_from_the_elements_is_an_inconsistency() -> None:
    image = figure()
    link = ElementRelationship(
        source_id=element(FAA).id,
        target_id=image.id,
        kind=RelationshipKind.CAPTION_OF,
    )

    with pytest.raises(DataInconsistencyError):
        select([figure_unit(image)], [image], [link])


def test_a_figure_missing_from_the_elements_is_an_inconsistency() -> None:
    with pytest.raises(DataInconsistencyError):
        select([text_unit(figure())], [])
