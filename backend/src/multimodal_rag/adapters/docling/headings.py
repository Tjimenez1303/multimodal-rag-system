"""Heading levels computed from signals that cover the whole document.

Docling's ``HeadingHierarchyModel.assign_heading_levels`` needs the whole converted
document and renumbers levels inside each conversion. The extractor converts page
batches so each job reports its progress per batch, so page batches of one document
would disagree. This module applies the same precedence Docling documents, the PDF
outline first and section numbering second, to the whole document at once, which
gives every heading its final level in the batch that contains it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

MAX_HEADING_LEVEL = 6
# Section numbers such as "4", "4.2" or "4.2.1." followed by the title. Four-digit
# numbers are left out so years are not read as sections.
_SECTION_NUMBER = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3})*)\.?\s+\S")


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    """One bookmark of the PDF outline.

    Attributes:
        depth: Nesting depth, 0 for top-level bookmarks.
        title: Text shown for the bookmark.
        page: 1-based page the bookmark points to, if any.
    """

    depth: int
    title: str
    page: int | None


class HeadingLevels:
    """Resolves the level of a heading from the outline or its section number.

    An outline whose top level holds a single bookmark, such as the "Structure
    Bookmarks" root of tagged PDFs, is treated as a wrapper, so its children start at
    level 1. A bookmark that repeats the title of its parent adds no level, because
    tagged PDFs nest each section under several bookmarks with the same title.

    Args:
        outline: Every bookmark of the document, in document order.
    """

    def __init__(self, outline: Sequence[OutlineEntry]) -> None:
        # Depth of every bookmark, with repeated parent titles collapsed
        depths = _effective_depths(outline)

        # A single top bookmark is the document title, so its children become level 1
        top = min(depths, default=0)
        if len(depths) > 1 and depths.count(top) == 1:
            top += 1
        self._by_page: dict[tuple[int | None, str], int] = {}
        self._by_title: dict[str, set[int]] = {}

        # Record the level of each bookmark by page and title, and by title alone
        for entry, depth in zip(outline, depths, strict=True):
            # Bookmarks above the top level are not headings
            if depth < top:
                continue
            level = min(depth - top + 1, MAX_HEADING_LEVEL)
            key = _normalized(entry.title)

            # The same title on one page keeps its shallowest level
            known = self._by_page.get((entry.page, key), level)
            self._by_page[(entry.page, key)] = min(known, level)
            self._by_title.setdefault(key, set()).add(level)

    def level_of(self, text: str, *, page: int) -> int:
        """Return the level of a heading, 1 being the outermost.

        Args:
            text: Heading text as extracted.
            page: 1-based page of the heading.

        Returns:
            The level of a bookmark with the same title on the same page, or of the
            only level that title has elsewhere, or the depth of its section number,
            or 1.
        """
        # An outline entry on the same page decides first
        key = _normalized(text)
        if (page, key) in self._by_page:
            return self._by_page[(page, key)]

        # Then a title that has one level anywhere in the outline
        levels = self._by_title.get(key, set())
        if len(levels) == 1:
            return next(iter(levels))

        # Then a section number such as 4.2.1, one level per number
        match = _SECTION_NUMBER.match(text)
        if match:
            return min(match.group(1).count(".") + 1, MAX_HEADING_LEVEL)

        # Otherwise it is a top-level heading
        return 1


def _effective_depths(outline: Sequence[OutlineEntry]) -> list[int]:
    # Walks the outline in document order with a stack of ancestors, so a bookmark
    # takes its parent's depth when both have the same title.
    ancestors: list[tuple[int, str, int]] = []
    depths = []
    for entry in outline:
        # Pop the ancestors that are not above this bookmark
        while ancestors and ancestors[-1][0] >= entry.depth:
            ancestors.pop()
        title = _normalized(entry.title)

        # Roots get depth 0, a child repeating its parent's title shares its depth
        if not ancestors:
            depth = 0
        elif ancestors[-1][1] == title:
            depth = ancestors[-1][2]
        else:
            depth = ancestors[-1][2] + 1
        ancestors.append((entry.depth, title, depth))
        depths.append(depth)
    return depths


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(" .:")
