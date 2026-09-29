"""Validation of the ``[n]`` markers the answer model writes.

A marker is kept only when ``n`` is the number of a supplied source, so an answer can
never cite a page that was not retrieved. Sources that share a document and pages
become one citation, and citations are renumbered in order of first appearance, with
the markers in the text rewritten to match.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from multimodal_rag.answering.domain import Citation
from multimodal_rag.ingestion.domain import RetrievalUnit

# A marker and the spaces before it, which go away with a removed marker.
_MARKER = re.compile(r"(?P<space>[ \t]*)\[(?P<number>\d+)\]")
# The same marker written twice in a row once merged sources share a number.
_REPEATED_MARKER = re.compile(r"(\[\d+\])(?:\1)+")


@dataclass(frozen=True, slots=True)
class CitedText:
    """The answer text with only valid markers, and what they cite.

    Attributes:
        text: The text with invalid markers removed and valid ones renumbered.
        citations: Citations numbered from 1 in order of first appearance.
        numbers: Citation number of every cited unit.
    """

    text: str
    citations: tuple[Citation, ...]
    numbers: dict[uuid.UUID, int]


def resolve_citations(
    text: str,
    units: Sequence[RetrievalUnit],
    *,
    document_names: Mapping[uuid.UUID, str],
) -> CitedText:
    """Keep the markers that point to supplied units and turn them into citations.

    Args:
        text: Answer text with ``[n]`` markers, where ``n`` numbers the supplied
            units from 1.
        units: Units supplied to the model, in the order they were numbered.
        document_names: File name of every document of the units.

    Returns:
        The rewritten text, its citations and the citation number of each cited
        unit. A text without a valid marker has no citations.
    """
    numbers: dict[tuple[uuid.UUID, tuple[int, ...]], int] = {}
    members: dict[int, list[RetrievalUnit]] = {}

    def renumber(marker: re.Match[str]) -> str:
        position = int(marker["number"])
        if not 1 <= position <= len(units):
            return ""
        cited = units[position - 1]
        number = numbers.setdefault((cited.document_id, cited.pages), len(numbers) + 1)
        if cited not in members.setdefault(number, []):
            members[number].append(cited)
        return f"{marker['space']}[{number}]"

    rewritten = _REPEATED_MARKER.sub(r"\1", _MARKER.sub(renumber, text))
    citations = tuple(
        Citation(
            number=number,
            document_id=cited[0].document_id,
            document_name=document_names[cited[0].document_id],
            pages=tuple(sorted(cited[0].pages)),
            unit_ids=tuple(unit.id for unit in cited),
        )
        for number, cited in members.items()
    )
    return CitedText(
        text=rewritten,
        citations=citations,
        numbers={
            unit.id: number for number, cited in members.items() for unit in cited
        },
    )
