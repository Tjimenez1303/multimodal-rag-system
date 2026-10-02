"""Selection of the figures shown with an answer.

Candidates are the figures of the cited units: a figure unit brings its own figure and
a text or table unit brings the figures ingestion found near it. The primary image is
the figure of the most relevant cited unit that sits closest to that unit's text on the
same page, and the other candidates are related images. Decorative figures and figures
without a stored crop are never returned.
"""

import math
import uuid
from collections.abc import Callable, Mapping, Sequence

from multimodal_rag.answering.domain import AnswerImage
from multimodal_rag.ingestion.domain import (
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    RelationshipKind,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.shared.errors import DataInconsistencyError


def select_images(
    cited_units: Sequence[RetrievalUnit],
    *,
    elements: Mapping[uuid.UUID, ExtractedElement],
    relationships: Sequence[ElementRelationship],
    document_names: Mapping[uuid.UUID, str],
) -> tuple[AnswerImage | None, tuple[AnswerImage, ...]]:
    """Pick the primary image and the related images of an answer.

    Args:
        cited_units: Units the answer cites, most relevant first.
        elements: Every element of those units and their figures, plus the captions
            named by ``relationships``.
        relationships: Relationships that touch the candidate figures.
        document_names: File name of every document of the units.

    Returns:
        The primary image, or ``None`` when no cited unit has a figure, and the
        related images by relevance, without the primary one.

    Raises:
        DataInconsistencyError: If a figure or a caption is missing from
            ``elements``.
    """
    # Caption id of every captioned figure
    captions = {
        link.target_id: link.source_id
        for link in relationships
        if link.kind is RelationshipKind.CAPTION_OF
    }

    # Walk the cited units in order, closest figure first within each unit
    images: dict[uuid.UUID, AnswerImage] = {}
    for unit in cited_units:
        for figure in sorted(_figures_of(unit, elements), key=_distance_to(unit)):
            # A figure shown for an earlier unit is not repeated
            if figure.id not in images:
                images[figure.id] = AnswerImage(
                    element_id=figure.id,
                    document_id=figure.document_id,
                    document_name=document_names[figure.document_id],
                    page=figure.page,
                    bbox=figure.bbox,
                    caption=_caption(figure, captions, elements),
                    unit_id=unit.id,
                )

    # The first figure is the primary image, the rest are related images
    ordered = tuple(images.values())
    return (ordered[0] if ordered else None), ordered[1:]


def figure_ids_of(unit: RetrievalUnit) -> tuple[uuid.UUID, ...]:
    """Return the ids of the elements that may be figures of a unit.

    Args:
        unit: A cited unit.

    Returns:
        Its own elements when it is a figure unit, followed by its nearby figures.
    """
    # A figure unit's own image, then the figures near its text
    own = unit.element_ids if unit.unit_type is UnitType.FIGURE else ()
    return (*own, *unit.figure_ids)


def _figures_of(
    unit: RetrievalUnit, elements: Mapping[uuid.UUID, ExtractedElement]
) -> list[ExtractedElement]:
    # Every figure a unit refers to must be stored
    missing = [i for i in figure_ids_of(unit) if i not in elements]
    if missing:
        raise DataInconsistencyError(f"Unit {unit.id} refers to missing figures")

    # Keep content images that have a stored crop
    candidates = (elements[element_id] for element_id in figure_ids_of(unit))
    return [
        candidate
        for candidate in candidates
        if candidate.kind is ElementKind.IMAGE
        and not candidate.is_decorative
        and candidate.image_key is not None
    ]


def _distance_to(
    unit: RetrievalUnit,
) -> Callable[[ExtractedElement], tuple[bool, float]]:
    own = set(unit.element_ids)

    def distance(figure: ExtractedElement) -> tuple[bool, float]:
        # A figure unit's own figure is the unit, so nothing is closer.
        if figure.id in own:
            return (False, 0.0)

        # Shortest gap to any box of the unit on the figure's page
        gaps = [
            box.bbox.gap_to(figure.bbox)
            for box in unit.boxes
            if box.page == figure.page
        ]

        # Figures on other pages sort after every figure on the same page
        return (not gaps, min(gaps, default=math.inf))

    return distance


def _caption(
    figure: ExtractedElement,
    captions: Mapping[uuid.UUID, uuid.UUID],
    elements: Mapping[uuid.UUID, ExtractedElement],
) -> str | None:
    # Return the caption text, if the figure has one
    caption_id = captions.get(figure.id)
    if caption_id is None:
        return None
    if caption_id not in elements:
        raise DataInconsistencyError(f"The caption of figure {figure.id} is missing")
    return elements[caption_id].text
