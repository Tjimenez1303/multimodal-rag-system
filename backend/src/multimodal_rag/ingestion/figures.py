"""Which figures deserve a description, and what the description may claim.

The filter needs a minimum share of the page area and rejects classifier labels that
mark decorations. Images repeated across pages are decorations too. The verifier flags
identifiers the vision model wrote that the figure's own labels and caption do not
contain.
"""

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    PageSize,
    RelationshipKind,
)

# Labels of Docling's DocumentFigureClassifier that mark decorations, not content.
DECORATIVE_CLASSES = frozenset(
    {
        "logo",
        "icon",
        "signature",
        "stamp",
        "bar_code",
        "qr_code",
        "full_page_image",
        "page_thumbnail",
    }
)
# Smallest share of its page a figure needs to be described.
MIN_DESCRIBED_AREA_SHARE = 0.05
# Words mixing digits with letters or hyphens, such as V-12, 12v or 5-3431-201-10.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class FigureTriage:
    """Outcome of the relevance filter.

    Attributes:
        elements: Every element, with decorative images flagged and skipped figures
            marked, in the input order.
        to_describe: Images to send to the vision model, in reading order.
    """

    elements: tuple[ExtractedElement, ...]
    to_describe: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class DescriptionContext:
    """Text given to the vision model together with a figure.

    Attributes:
        caption: Caption of the figure, if any.
        context: Nearby text, if any.
    """

    caption: str | None
    context: str | None


@dataclass(frozen=True, slots=True)
class FigurePolicy:
    """Decides which images are decorative and which are described.

    Attributes:
        decorative_min_pages: Pages an image must repeat on to be decorative.
        decorative_min_page_share: Share of the pages an image must repeat on to be
            decorative.
    """

    decorative_min_pages: int
    decorative_min_page_share: float

    def triage(
        self,
        elements: Sequence[ExtractedElement],
        *,
        image_hashes: Mapping[uuid.UUID, str],
        page_sizes: Mapping[int, PageSize],
        pages_total: int,
        describe: bool,
    ) -> FigureTriage:
        """Flag decorative images and choose the figures to describe.

        Args:
            elements: Elements of the whole document.
            image_hashes: Fingerprint of the stored crop of each image.
            page_sizes: Size of every page.
            pages_total: Pages in the document.
            describe: Whether figure description is enabled.

        Returns:
            The updated elements and the images to describe.

        Raises:
            UnknownPageSizeError: If an image lies on a page of unknown size.
        """
        repeated = self._repeated(elements, image_hashes, pages_total)
        updated: list[ExtractedElement] = []
        chosen: list[uuid.UUID] = []
        for element in elements:
            if element.kind is not ElementKind.IMAGE:
                updated.append(element)
                continue
            if element.image_class in DECORATIVE_CLASSES or element.id in repeated:
                element = element.as_decorative()
            if describe and _worth_describing(element, image_hashes, page_sizes):
                chosen.append(element.id)
            else:
                element = element.with_description(status=DescriptionStatus.SKIPPED)
            updated.append(element)
        return FigureTriage(elements=tuple(updated), to_describe=tuple(chosen))

    def _repeated(
        self,
        elements: Sequence[ExtractedElement],
        image_hashes: Mapping[uuid.UUID, str],
        pages_total: int,
    ) -> set[uuid.UUID]:
        pages_by_hash: dict[str, set[int]] = defaultdict(set)
        ids_by_hash: dict[str, list[uuid.UUID]] = defaultdict(list)
        for element in elements:
            fingerprint = image_hashes.get(element.id)
            if element.kind is ElementKind.IMAGE and fingerprint is not None:
                pages_by_hash[fingerprint].add(element.page)
                ids_by_hash[fingerprint].append(element.id)
        repeated: set[uuid.UUID] = set()
        for fingerprint, pages in pages_by_hash.items():
            share = len(pages) / max(pages_total, 1)
            if len(pages) > 1 and (
                len(pages) >= self.decorative_min_pages
                or share >= self.decorative_min_page_share
            ):
                repeated.update(ids_by_hash[fingerprint])
        return repeated


def unverified_identifiers(
    description: str, *, labels: Sequence[str], caption: str | None
) -> tuple[str, ...]:
    """Return identifiers of a description that the figure itself does not show.

    Args:
        description: Text written by the vision model.
        labels: Text printed inside the figure.
        caption: Caption of the figure, if any.

    Returns:
        Identifiers absent from the labels and the caption, in order of appearance,
        compared without regard to case.
    """
    known = " ".join((*labels, caption or "")).casefold()
    unverified: dict[str, None] = {}
    for token in _TOKEN.findall(description):
        is_identifier = any(c.isdigit() for c in token) and (
            "-" in token or any(c.isalpha() for c in token)
        )
        if is_identifier and token.casefold() not in known:
            unverified.setdefault(token)
    return tuple(unverified)


def description_context(
    image: ExtractedElement,
    *,
    elements: Mapping[uuid.UUID, ExtractedElement],
    relationships: Sequence[ElementRelationship],
) -> DescriptionContext:
    """Collect the caption and nearby text that accompany a figure.

    Args:
        image: Figure to describe.
        elements: Elements of the document by id.
        relationships: Relationships of the document.

    Returns:
        The caption and the nearby text, each joined in reading order.
    """

    def joined(kind: RelationshipKind) -> str | None:
        sources = sorted(
            (
                elements[link.source_id]
                for link in relationships
                if link.kind is kind and link.target_id == image.id
            ),
            key=lambda element: element.reading_order,
        )
        texts = [element.text for element in sources if element.text]
        return "\n".join(texts) or None

    return DescriptionContext(
        caption=joined(RelationshipKind.CAPTION_OF),
        context=joined(RelationshipKind.NEAR),
    )


def _worth_describing(
    image: ExtractedElement,
    image_hashes: Mapping[uuid.UUID, str],
    page_sizes: Mapping[int, PageSize],
) -> bool:
    if image.is_decorative or image.id not in image_hashes:
        return False
    page = PageSize.of_page(page_sizes, image.page)
    return image.bbox.area / page.area >= MIN_DESCRIBED_AREA_SHARE
