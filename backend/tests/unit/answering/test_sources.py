import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from multimodal_rag.answering.domain import RetrievedSource
from multimodal_rag.answering.sources import assemble_sources
from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    ExtractedElement,
    TextOrigin,
    UnitType,
)
from multimodal_rag.ingestion.ports import SearchHit
from multimodal_rag.shared.errors import DataInconsistencyError
from tests.library import document, element, hit, unit

TM = document("tm-5-3431.pdf")
NAMES = {TM.id: TM.file_name}


def assemble(
    hits: Sequence[SearchHit],
    elements: Sequence[ExtractedElement],
    numbers: dict[uuid.UUID, int] | None = None,
) -> tuple[RetrievedSource, ...]:
    return assemble_sources(
        hits,
        elements={e.id: e for e in elements},
        document_names=NAMES,
        citation_numbers=numbers or {},
        low_confidence_threshold=0.90,
    )


def recognized(confidence: float) -> ExtractedElement:
    return element(TM, origin=TextOrigin.RECOGNIZED, confidence=confidence)


def figure(**values: Any) -> ExtractedElement:
    return element(TM, kind=ElementKind.IMAGE, image_key="figures/x.png", **values)


def test_a_source_describes_its_unit_rank_and_similarity() -> None:
    paragraph = element(TM, page=13)
    text_unit = unit(
        TM, "Code SPL-480 means low oil.", members=[paragraph], heading_path=("Codes",)
    )

    [source] = assemble([hit(text_unit, similarity=0.42)], [paragraph])

    assert source == RetrievedSource(
        unit_id=text_unit.id,
        rank=1,
        similarity=0.42,
        document_id=TM.id,
        document_name="tm-5-3431.pdf",
        section=("Codes",),
        pages=(13,),
        content_type=UnitType.TEXT,
        excerpt="Code SPL-480 means low oil.",
        citation_number=None,
        low_confidence_text=False,
        generated_description=False,
        unverified_identifiers=(),
        tables=(),
        figure_ids=(),
    )


def test_the_excerpt_holds_the_first_300_characters() -> None:
    paragraph = element(TM)
    long_unit = unit(TM, "x" * 299 + "yz" + "w" * 500, members=[paragraph])

    [source] = assemble([hit(long_unit)], [paragraph])

    assert source.excerpt == "x" * 299 + "y"


@pytest.mark.parametrize(
    ("confidence", "flagged"), [(0.8999, True), (0.90, False), (0.99, False)]
)
def test_recognized_text_below_the_threshold_is_flagged(
    confidence: float, flagged: bool
) -> None:
    confident, doubtful = recognized(0.99), recognized(confidence)
    scanned = unit(TM, "Scanned text.", members=[confident, doubtful])

    [source] = assemble([hit(scanned)], [confident, doubtful])

    assert source.low_confidence_text is flagged


def test_text_layer_elements_are_never_flagged() -> None:
    digital = element(TM)

    [source] = assemble([hit(unit(TM, "Digital.", members=[digital]))], [digital])

    assert source.low_confidence_text is False


def test_a_described_figure_is_a_generated_description_with_its_identifiers() -> None:
    image = figure(
        description="A valve V-12 feeds pump P-7.",
        description_status=DescriptionStatus.DESCRIBED,
        unverified_identifiers=("P-7",),
    )
    caption = element(TM, kind=ElementKind.CAPTION)
    figure_unit = unit(
        TM,
        "Figure 3. Fuel\nA valve.",
        members=[image, caption],
        unit_type=UnitType.FIGURE,
    )

    [source] = assemble([hit(figure_unit)], [image, caption])

    assert source.content_type is UnitType.FIGURE
    assert source.generated_description is True
    assert source.unverified_identifiers == ("P-7",)
    assert source.figure_ids == (image.id,)


def test_a_figure_that_was_not_described_is_not_a_generated_description() -> None:
    image = figure(description_status=DescriptionStatus.NOT_DESCRIBED)
    figure_unit = unit(TM, "Figure 3.", members=[image], unit_type=UnitType.FIGURE)

    [source] = assemble([hit(figure_unit)], [image])

    assert source.generated_description is False
    assert source.unverified_identifiers == ()


def test_the_citation_number_comes_from_the_citations() -> None:
    first, second = element(TM), element(TM)
    cited, uncited = (
        unit(TM, "Cited.", members=[first]),
        unit(TM, "Not cited.", members=[second]),
    )

    sources = assemble([hit(cited), hit(uncited)], [first, second], {cited.id: 1})

    assert [(s.rank, s.citation_number) for s in sources] == [(1, 1), (2, None)]


def test_figure_ids_list_the_non_decorative_figures_of_the_unit() -> None:
    paragraph = element(TM)
    drawing, logo = figure(), figure(is_decorative=True)
    text_unit = unit(
        TM, "See the drawing.", members=[paragraph], figure_ids=(drawing.id, logo.id)
    )

    [source] = assemble([hit(text_unit)], [paragraph, drawing, logo])

    assert source.figure_ids == (drawing.id,)


def test_an_element_missing_from_the_repository_is_an_inconsistency() -> None:
    paragraph = element(TM)

    with pytest.raises(DataInconsistencyError):
        assemble([hit(unit(TM, "Orphan.", members=[paragraph]))], [])
