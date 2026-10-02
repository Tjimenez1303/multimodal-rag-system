"""Validation of the ``[n]`` markers the answer model writes.

A marker is kept only when ``n`` is the number of a supplied source, so an answer can
never cite a page that was not retrieved. Sources that share a document and pages
become one citation, and citations are renumbered in order of first appearance, with
the markers in the text rewritten to match. The variants models also write, such as
``[1, 3]``, ``[1-3]``, ``[[1]]`` and ``【1】``, are first rewritten to separate markers,
as Onyx, RAGFlow and Open WebUI accept them.
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from multimodal_rag.answering.domain import Citation
from multimodal_rag.ingestion.domain import RetrievalUnit

# A marker and the spaces before it, which go away with a removed marker.
_MARKER = re.compile(r"(?P<space>[ \t]*)\[(?P<number>\d+)\]")
# Doubled or wide brackets, and lists or ranges of numbers inside one pair of brackets.
_VARIANT = re.compile(
    r"\[\[(?P<doubled>\d+)\]\]|【(?P<wide>\d+)】"
    r"|\[(?P<group>\d+(?:\s*[,\-–]\s*\d+)+)\]"
)
_RANGE = re.compile(r"(?P<first>\d+)\s*[\-–]\s*(?P<last>\d+)")
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
    # Rewrite variants such as [[2]] or [1-3] as plain markers first
    text = _separate_variants(text, sources=len(units))

    # One number per cited document and page set, and the units behind each number
    numbers: dict[tuple[uuid.UUID, tuple[int, ...]], int] = {}
    members: dict[int, list[RetrievalUnit]] = {}

    def renumber(marker: re.Match[str]) -> str:
        # Drop markers that point past the supplied sources
        position = int(marker["number"])
        if not 1 <= position <= len(units):
            return ""

        # Units on the same pages of the same document share one number
        cited = units[position - 1]
        number = numbers.setdefault((cited.document_id, cited.pages), len(numbers) + 1)
        if cited not in members.setdefault(number, []):
            members[number].append(cited)
        return f"{marker['space']}[{number}]"

    # Renumber every marker, then merge the repeats the merge produced
    rewritten = _REPEATED_MARKER.sub(r"\1", _MARKER.sub(renumber, text))

    # Turn each number into a citation of its document and pages
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


def has_markers(text: str) -> bool:
    """Return whether a text holds a source marker in any accepted form.

    Args:
        text: Answer text written by the model.

    Returns:
        ``True`` when the text holds at least one marker, valid or not.
    """
    return bool(_MARKER.search(text) or _VARIANT.search(text))


def _separate_variants(text: str, *, sources: int) -> str:
    def separate(variant: re.Match[str]) -> str:
        # A doubled or wide bracket holds a single number
        single = variant["doubled"] or variant["wide"]
        if single is not None:
            return f"[{single}]"

        # A group lists numbers and ranges, each becoming its own marker
        numbers: list[int] = []
        for part in re.split(r"\s*,\s*", variant["group"]):
            if (span := _RANGE.fullmatch(part)) is not None:
                # A range never expands past the supplied sources.
                last = min(int(span["last"]), sources)
                numbers += range(int(span["first"]), last + 1)
            else:
                numbers.append(int(part))
        return "".join(f"[{number}]" for number in numbers)

    return _VARIANT.sub(separate, text)
