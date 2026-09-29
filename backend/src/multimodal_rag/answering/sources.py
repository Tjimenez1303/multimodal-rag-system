"""The retrieved sources listed with an answer, one per unit supplied to the model.

Each source carries what a reader needs to judge it: where it comes from, an excerpt,
whether the answer cites it, and flags from the elements ingestion stored, such as text
recognized with low confidence or a figure description written by a model. A table
unit carries the rows of each of its parts, so a client can render it as a table.
"""

import uuid
from collections.abc import Mapping, Sequence

from multimodal_rag.answering.domain import RetrievedSource, TableContent
from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    ExtractedElement,
    RetrievalUnit,
    TextOrigin,
    UnitType,
)
from multimodal_rag.ingestion.ports import SearchHit
from multimodal_rag.shared.errors import DataInconsistencyError

EXCERPT_CHARS = 300


def elements_of(unit: RetrievalUnit) -> tuple[uuid.UUID, ...]:
    """Return the ids of every element a source reads for a unit.

    Args:
        unit: A retrieved unit.

    Returns:
        Its own elements followed by its associated figures.
    """
    return (*unit.element_ids, *unit.figure_ids)


def assemble_sources(
    hits: Sequence[SearchHit],
    *,
    elements: Mapping[uuid.UUID, ExtractedElement],
    document_names: Mapping[uuid.UUID, str],
    citation_numbers: Mapping[uuid.UUID, int],
    low_confidence_threshold: float,
) -> tuple[RetrievedSource, ...]:
    """Describe every supplied unit in rank order.

    Args:
        hits: Units supplied to the model, best first.
        elements: Every element returned by ``elements_of`` for those units.
        document_names: File name of every document of the units.
        citation_numbers: Citation number of every cited unit.
        low_confidence_threshold: Recognition confidence below which a source is
            flagged.

    Returns:
        One source per hit, ranked from 1.

    Raises:
        DataInconsistencyError: If an element of a unit is missing.
    """
    sources = []
    for rank, hit in enumerate(hits, start=1):
        unit = hit.unit
        members = _members(unit, elements)
        described = _described_figure(unit, members)
        sources.append(
            RetrievedSource(
                unit_id=unit.id,
                rank=rank,
                similarity=hit.similarity,
                document_id=unit.document_id,
                document_name=document_names[unit.document_id],
                section=unit.heading_path,
                pages=unit.pages,
                content_type=unit.unit_type,
                excerpt=unit.text[:EXCERPT_CHARS],
                citation_number=citation_numbers.get(unit.id),
                low_confidence_text=any(
                    member.origin is TextOrigin.RECOGNIZED
                    and member.confidence is not None
                    and member.confidence < low_confidence_threshold
                    for member in members
                ),
                generated_description=described is not None,
                unverified_identifiers=(
                    () if described is None else described.unverified_identifiers
                ),
                tables=_tables(unit, members),
                figure_ids=_figure_ids(unit, elements),
            )
        )
    return tuple(sources)


def _members(
    unit: RetrievalUnit, elements: Mapping[uuid.UUID, ExtractedElement]
) -> tuple[ExtractedElement, ...]:
    missing = [i for i in elements_of(unit) if i not in elements]
    if missing:
        raise DataInconsistencyError(f"Unit {unit.id} refers to missing elements")
    return tuple(elements[element_id] for element_id in unit.element_ids)


def _described_figure(
    unit: RetrievalUnit, members: Sequence[ExtractedElement]
) -> ExtractedElement | None:
    if unit.unit_type is not UnitType.FIGURE:
        return None
    return next(
        (
            member
            for member in members
            if member.description_status is DescriptionStatus.DESCRIBED
        ),
        None,
    )


def _tables(
    unit: RetrievalUnit, members: Sequence[ExtractedElement]
) -> tuple[TableContent, ...]:
    if unit.unit_type is not UnitType.TABLE:
        return ()
    return tuple(
        TableContent(page=member.page, rows=member.table)
        for member in members
        if member.table is not None
    )


def _figure_ids(
    unit: RetrievalUnit, elements: Mapping[uuid.UUID, ExtractedElement]
) -> tuple[uuid.UUID, ...]:
    # A figure unit's own image comes first, then the figures near its text.
    candidates = (elements[element_id] for element_id in elements_of(unit))
    return tuple(
        dict.fromkeys(
            candidate.id
            for candidate in candidates
            if candidate.kind is ElementKind.IMAGE and not candidate.is_decorative
        )
    )
