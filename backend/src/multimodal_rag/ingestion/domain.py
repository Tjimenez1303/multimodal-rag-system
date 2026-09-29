"""Domain model of document ingestion.

Entities are immutable dataclasses. State changes return a new instance through methods
that enforce the rules of the data model, so an invalid state can never be built. This
module imports nothing outside the standard library and the project's own errors.
"""

import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from multimodal_rag.ingestion.errors import (
    ElementWithoutPositionError,
    InvalidBoundingBoxError,
    InvalidDocumentError,
    InvalidElementError,
    InvalidJobTransitionError,
    InvalidPageSizeError,
    JobNotLeasedError,
    UnknownPageSizeError,
)

# Random application namespace for UUIDv5 ids, generated once. It must never change:
# every stored element and unit id derives from it.
ID_NAMESPACE = uuid.UUID("e7ff7153-60c1-4d27-ab14-b11734f890b0")

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_FILE_NAME_LENGTH = 255


class JobStatus(StrEnum):
    """Lifecycle state of an ingestion job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(StrEnum):
    """Step a processing job is currently running."""

    EXTRACTING = "extracting"
    DESCRIBING_FIGURES = "describing_figures"
    BUILDING_UNITS = "building_units"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    FINALIZING = "finalizing"


class FailureCode(StrEnum):
    """Machine-readable cause of a failed job."""

    ENCRYPTED_DOCUMENT = "encrypted_document"
    CORRUPT_DOCUMENT = "corrupt_document"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INTERRUPTED_REPEATEDLY = "interrupted_repeatedly"
    INTERNAL_ERROR = "internal_error"


class ElementKind(StrEnum):
    """Type of an extracted element."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    TABLE = "table"
    IMAGE = "image"
    PAGE_FURNITURE = "page_furniture"


class TextOrigin(StrEnum):
    """Where the text of an element came from."""

    TEXT_LAYER = "text_layer"
    RECOGNIZED = "recognized"


class DescriptionStatus(StrEnum):
    """Outcome of describing an image with the vision model."""

    DESCRIBED = "described"
    SKIPPED = "skipped"
    NOT_DESCRIBED = "not_described"


class RelationshipKind(StrEnum):
    """Kind of link between two extracted elements."""

    CAPTION_OF = "caption_of"
    TITLE_OF = "title_of"
    DESCRIBES = "describes"
    NEAR = "near"
    CONTINUES = "continues"


class UnitType(StrEnum):
    """Type of a retrieval unit."""

    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"


def element_id_for(*, document_sha256: str, element_key: str) -> uuid.UUID:
    """Return the deterministic id of an element.

    Args:
        document_sha256: Fingerprint of the document the element belongs to.
        element_key: Key that identifies the element within the document.

    Returns:
        A UUID that is identical every time the same document is processed.
    """
    return uuid.uuid5(ID_NAMESPACE, f"element:{document_sha256}:{element_key}")


def unit_id_for(*, document_sha256: str, unit_key: str) -> uuid.UUID:
    """Return the deterministic id of a retrieval unit.

    Args:
        document_sha256: Fingerprint of the document the unit belongs to.
        unit_key: Key that identifies the unit within the document.

    Returns:
        A UUID that is identical every time the same document is processed.
    """
    return uuid.uuid5(ID_NAMESPACE, f"unit:{document_sha256}:{unit_key}")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Rectangle on a page in PDF points with a top-left origin.

    Attributes:
        left: Distance from the left edge of the page.
        top: Distance from the top edge of the page.
        right: Distance from the left edge to the right side of the box.
        bottom: Distance from the top edge to the bottom side of the box.
    """

    left: float
    top: float
    right: float
    bottom: float

    origin = "top_left"

    def __post_init__(self) -> None:
        """Reject boxes with non-finite, negative or inverted coordinates."""
        values = (self.left, self.top, self.right, self.bottom)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise InvalidBoundingBoxError(
                f"Coordinates must be finite and >= 0: {values}"
            )
        if self.left >= self.right or self.top >= self.bottom:
            raise InvalidBoundingBoxError(f"Box edges are inverted or empty: {values}")

    @classmethod
    def on_page(
        cls,
        *,
        left: float,
        top: float,
        right: float,
        bottom: float,
        page_width: float,
        page_height: float,
        tolerance: float = 1.0,
    ) -> BoundingBox:
        """Build a box that must lie within its page.

        Extraction models round coordinates, so a box may overshoot the page by up to
        ``tolerance`` points and is then clamped to the page edges.

        Args:
            left: Left edge in PDF points.
            top: Top edge in PDF points.
            right: Right edge in PDF points.
            bottom: Bottom edge in PDF points.
            page_width: Width of the page in PDF points.
            page_height: Height of the page in PDF points.
            tolerance: Largest overshoot, in points, that is clamped instead of
                rejected.

        Returns:
            The validated box, clamped to the page.

        Raises:
            InvalidBoundingBoxError: If the box lies outside the page by more than the
                tolerance or has inverted edges.
        """
        if (
            min(left, top) < -tolerance
            or right > page_width + tolerance
            or bottom > page_height + tolerance
        ):
            raise InvalidBoundingBoxError(
                f"Box ({left}, {top}, {right}, {bottom}) lies outside a "
                f"{page_width}x{page_height} page"
            )
        return cls(
            left=max(left, 0.0),
            top=max(top, 0.0),
            right=min(right, page_width),
            bottom=min(bottom, page_height),
        )

    @property
    def width(self) -> float:
        """Horizontal size of the box."""
        return self.right - self.left

    @property
    def height(self) -> float:
        """Vertical size of the box."""
        return self.bottom - self.top

    @property
    def area(self) -> float:
        """Surface of the box in square points."""
        return self.width * self.height

    def gap_to(self, other: BoundingBox) -> float:
        """Return the shortest distance to another box on the same page.

        Args:
            other: Box to measure the distance to.

        Returns:
            The distance in PDF points between the closest edges or corners, 0 when
            the boxes touch or overlap.
        """
        horizontal = max(0.0, other.left - self.right, self.left - other.right)
        vertical = max(0.0, other.top - self.bottom, self.top - other.bottom)
        return math.hypot(horizontal, vertical)


@dataclass(frozen=True, slots=True)
class PageSize:
    """Size of a page in PDF points.

    Attributes:
        width: Horizontal size of the page.
        height: Vertical size of the page.
    """

    width: float
    height: float

    def __post_init__(self) -> None:
        """Reject sizes that are not positive and finite."""
        if not all(
            math.isfinite(value) and value > 0 for value in (self.width, self.height)
        ):
            raise InvalidPageSizeError(
                f"Page size must be positive and finite: {self.width}x{self.height}"
            )

    @property
    def area(self) -> float:
        """Surface of the page in square points."""
        return self.width * self.height

    @staticmethod
    def of_page(page_sizes: Mapping[int, PageSize], page: int) -> PageSize:
        """Return the size of a page reported by the extractor.

        Args:
            page_sizes: Size of each 1-based page.
            page: Page to look up.

        Returns:
            The size of the page.

        Raises:
            UnknownPageSizeError: If the page has no reported size.
        """
        try:
            return page_sizes[page]
        except KeyError:
            raise UnknownPageSizeError(f"Page {page} has no known size") from None


@dataclass(frozen=True, slots=True)
class Document:
    """An uploaded PDF identified by the fingerprint of its bytes.

    Attributes:
        id: Id generated on registration.
        sha256: Lowercase hex SHA-256 of the file bytes, 64 characters.
        file_name: Original name as uploaded, at most 255 characters.
        size_bytes: Size of the file.
        page_count: Page count read at upload, or ``None`` for encrypted files.
        blob_key: Storage key of the original PDF.
        created_at: Registration time.
    """

    id: uuid.UUID
    sha256: str
    file_name: str
    size_bytes: int
    page_count: int | None
    blob_key: str
    created_at: datetime

    def __post_init__(self) -> None:
        """Enforce the identity and size rules of a document."""
        if not _SHA256_PATTERN.fullmatch(self.sha256):
            raise InvalidDocumentError("sha256 must be 64 lowercase hex characters")
        if not 0 < len(self.file_name) <= MAX_FILE_NAME_LENGTH:
            raise InvalidDocumentError(
                f"file_name must have 1 to {MAX_FILE_NAME_LENGTH} characters"
            )
        if self.size_bytes <= 0:
            raise InvalidDocumentError("size_bytes must be positive")
        if self.page_count is not None and self.page_count < 1:
            raise InvalidDocumentError("page_count must be at least 1 when known")

    @staticmethod
    def blob_key_for(sha256: str) -> str:
        """Return the content-addressed storage key of a document.

        Args:
            sha256: Fingerprint of the document.

        Returns:
            The key ``documents/{sha256}.pdf``.
        """
        return f"documents/{sha256}.pdf"


@dataclass(frozen=True, slots=True)
class JobSummary:
    """Counts reported by a completed job.

    Attributes:
        pages: Pages processed.
        text_elements: Headings, paragraphs, list items and captions.
        tables: Table elements, counting each part of a split table.
        table_chains: Tables that continue across pages.
        images: Image elements.
        figures_described: Images with a generated description.
        figures_skipped: Decorative or irrelevant images not sent to the model.
        figures_not_described: Relevant images whose description failed.
        retrieval_units: Units written to the index.
        recognized_pages: Pages whose text came from recognition.
    """

    pages: int = 0
    text_elements: int = 0
    tables: int = 0
    table_chains: int = 0
    images: int = 0
    figures_described: int = 0
    figures_skipped: int = 0
    figures_not_described: int = 0
    retrieval_units: int = 0
    recognized_pages: int = 0


_OPEN_STATES = frozenset({JobStatus.PENDING, JobStatus.PROCESSING})


@dataclass(frozen=True, slots=True)
class IngestionJob:
    """One ingestion request for a document, run in at most ``max_attempts`` attempts.

    Attributes:
        id: Id returned to the client as ``job_id``.
        document_id: Document being ingested.
        status: Lifecycle state.
        max_attempts: Attempts allowed before the job fails.
        correlation_id: Request id of the upload that created the job.
        created_at: Creation time.
        updated_at: Time of the last change.
        stage: Current step while processing.
        pages_total: Pages to process, known once extraction starts.
        pages_done: Pages processed in the current attempt.
        attempt: Number of claims so far.
        lease_token: Fencing token of the current attempt.
        lease_expires_at: End of the current lease.
        worker_id: Holder of the current lease, for diagnostics.
        failure_code: Cause of the failure, set only when failed.
        failure_reason: Human-readable failure reason without document content.
        summary: Counts, set only when completed.
        started_at: Time of the first claim.
        finished_at: Time the job reached a terminal state.
    """

    id: uuid.UUID
    document_id: uuid.UUID
    status: JobStatus
    max_attempts: int
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    stage: JobStage | None = None
    pages_total: int | None = None
    pages_done: int = 0
    attempt: int = 0
    lease_token: uuid.UUID | None = None
    lease_expires_at: datetime | None = None
    worker_id: str | None = None
    failure_code: FailureCode | None = None
    failure_reason: str | None = None
    summary: JobSummary | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        job_id: uuid.UUID,
        document_id: uuid.UUID,
        max_attempts: int,
        correlation_id: str,
        now: datetime,
    ) -> IngestionJob:
        """Create a pending job.

        Args:
            job_id: Id to assign.
            document_id: Document to ingest.
            max_attempts: Attempts allowed before the job fails.
            correlation_id: Request id of the upload.
            now: Creation time.

        Returns:
            A job in the ``pending`` state.
        """
        return cls(
            id=job_id,
            document_id=document_id,
            status=JobStatus.PENDING,
            max_attempts=max_attempts,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )

    @property
    def is_terminal(self) -> bool:
        """Whether the job has completed or failed."""
        return self.status not in _OPEN_STATES

    @property
    def attempts_exhausted(self) -> bool:
        """Whether another claim would exceed the attempt limit."""
        return self.attempt >= self.max_attempts

    def held_lease(self) -> uuid.UUID:
        """Return the fencing token of the attempt that holds the job.

        Returns:
            The lease token of the current attempt.

        Raises:
            JobNotLeasedError: If the job was handed over without a claim.
        """
        if self.lease_token is None:
            raise JobNotLeasedError(f"Job {self.id} was not claimed")
        return self.lease_token

    def claim(
        self,
        *,
        lease_token: uuid.UUID,
        lease_expires_at: datetime,
        worker_id: str,
        now: datetime,
    ) -> IngestionJob:
        """Start a new attempt under a fresh lease.

        A pending job starts processing, and a processing job whose lease expired is
        reclaimed without leaving the ``processing`` state.

        Args:
            lease_token: Fencing token of the new attempt.
            lease_expires_at: End of the new lease.
            worker_id: Worker taking the job.
            now: Claim time.

        Returns:
            The job in ``processing`` with the attempt counter incremented.

        Raises:
            InvalidJobTransitionError: If the job is terminal or has no attempt left.
        """
        self._require_open("claim")
        if self.attempts_exhausted:
            raise InvalidJobTransitionError(
                f"Job {self.id} has used its {self.max_attempts} attempts"
            )
        return replace(
            self,
            status=JobStatus.PROCESSING,
            attempt=self.attempt + 1,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            worker_id=worker_id,
            stage=None,
            pages_done=0,
            started_at=self.started_at or now,
            updated_at=now,
        )

    def advance(
        self,
        *,
        stage: JobStage,
        pages_done: int,
        pages_total: int | None,
        now: datetime,
    ) -> IngestionJob:
        """Record progress of the current attempt.

        Args:
            stage: Step being run.
            pages_done: Pages processed so far in this attempt.
            pages_total: Pages to process, when known.
            now: Update time.

        Returns:
            The job with the new stage and progress.

        Raises:
            InvalidJobTransitionError: If the job is not processing or the page counts
                are inconsistent.
        """
        self._require_status(JobStatus.PROCESSING, "advance")
        if pages_done < 0 or (pages_total is not None and pages_done > pages_total):
            raise InvalidJobTransitionError(
                f"pages_done={pages_done} is outside 0..{pages_total}"
            )
        return replace(
            self,
            stage=stage,
            pages_done=pages_done,
            pages_total=pages_total,
            updated_at=now,
        )

    def complete(self, *, summary: JobSummary, now: datetime) -> IngestionJob:
        """Finish the job successfully.

        Args:
            summary: Counts of what was captured.
            now: Completion time.

        Returns:
            The job in ``completed`` with its lease released.

        Raises:
            InvalidJobTransitionError: If the job is not processing.
        """
        self._require_status(JobStatus.PROCESSING, "complete")
        return replace(
            self,
            status=JobStatus.COMPLETED,
            summary=summary,
            stage=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )

    def fail(self, *, code: FailureCode, reason: str, now: datetime) -> IngestionJob:
        """Finish the job with a failure.

        Args:
            code: Machine-readable cause.
            reason: Human-readable reason without document content.
            now: Failure time.

        Returns:
            The job in ``failed`` with its lease released.

        Raises:
            InvalidJobTransitionError: If the job is already terminal or the reason is
                empty.
        """
        self._require_open("fail")
        if not reason.strip():
            raise InvalidJobTransitionError(
                "A failed job needs a human-readable reason"
            )
        return replace(
            self,
            status=JobStatus.FAILED,
            failure_code=code,
            failure_reason=reason,
            stage=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )

    def fail_interrupted(self, *, now: datetime) -> IngestionJob:
        """Finish a job whose every allowed attempt was interrupted.

        Args:
            now: Failure time.

        Returns:
            The job in ``failed`` with ``interrupted_repeatedly``.

        Raises:
            InvalidJobTransitionError: If the job is already terminal.
        """
        return self.fail(
            code=FailureCode.INTERRUPTED_REPEATEDLY,
            reason=(
                "Processing was interrupted repeatedly. "
                f"Attempts used: {self.attempt} of {self.max_attempts}."
            ),
            now=now,
        )

    def _require_open(self, action: str) -> None:
        if self.is_terminal:
            raise InvalidJobTransitionError(
                f"Cannot {action} job {self.id} in state {self.status}"
            )

    def _require_status(self, status: JobStatus, action: str) -> None:
        if self.status is not status:
            raise InvalidJobTransitionError(
                f"Cannot {action} job {self.id} in state {self.status}"
            )


_IMAGE_ONLY_FIELDS = ("image_key", "image_class", "description", "description_status")


@dataclass(frozen=True, slots=True)
class ExtractedElement:
    """A typed piece of content taken from one page.

    Attributes:
        id: Deterministic id, see ``element_id_for``.
        document_id: Document the element belongs to.
        kind: Type of content.
        page: 1-based page number.
        bbox: Position on the page.
        reading_order: Order within the document.
        origin: Whether text came from the text layer or from recognition.
        heading_level: Level of a heading, only for headings.
        text: Text content, or the serialized table for tables.
        table: Rows of cell text, only for tables.
        confidence: Recognition confidence from 0 to 1, only for recognized text.
        image_key: Storage key of the crop, only for images.
        image_class: Classifier label, only for images.
        labels: Text printed inside the image, only for images.
        description: Generated description, only for images.
        description_status: Outcome of the description, only for images.
        unverified_identifiers: Identifiers in the description missing from the
            labels and the caption.
        is_decorative: Whether the image is a logo, stamp, repeated decoration or
            full-page scan.
    """

    id: uuid.UUID
    document_id: uuid.UUID
    kind: ElementKind
    page: int
    bbox: BoundingBox
    reading_order: int
    origin: TextOrigin = TextOrigin.TEXT_LAYER
    heading_level: int | None = None
    text: str | None = None
    table: tuple[tuple[str, ...], ...] | None = None
    confidence: float | None = None
    image_key: str | None = None
    image_class: str | None = None
    labels: tuple[str, ...] = field(default=())
    description: str | None = None
    description_status: DescriptionStatus | None = None
    unverified_identifiers: tuple[str, ...] = field(default=())
    is_decorative: bool = False

    def __post_init__(self) -> None:
        """Enforce position and kind-specific fields."""
        if not isinstance(self.page, int) or self.page < 1:
            raise ElementWithoutPositionError(f"Element {self.id} has no valid page")
        if not isinstance(self.bbox, BoundingBox):
            raise ElementWithoutPositionError(f"Element {self.id} has no bounding box")
        if self.confidence is not None and (
            self.origin is not TextOrigin.RECOGNIZED or not 0 <= self.confidence <= 1
        ):
            raise InvalidElementError(
                f"Element {self.id}: confidence is 0..1 and only for recognized text"
            )
        if (self.heading_level is not None) != (self.kind is ElementKind.HEADING):
            raise InvalidElementError(
                f"Element {self.id}: heading_level is required for headings only"
            )
        if self.table is not None and self.kind is not ElementKind.TABLE:
            raise InvalidElementError(f"Element {self.id}: table data on a {self.kind}")
        if self.kind is not ElementKind.IMAGE and (
            any(getattr(self, name) is not None for name in _IMAGE_ONLY_FIELDS)
            or self.labels
            or self.unverified_identifiers
            or self.is_decorative
        ):
            raise InvalidElementError(
                f"Element {self.id}: image fields on a {self.kind}"
            )

    @staticmethod
    def image_key_for(*, document_id: uuid.UUID, element_id: uuid.UUID) -> str:
        """Return the storage key of an image element's crop.

        Args:
            document_id: Document the image belongs to.
            element_id: Id of the image element.

        Returns:
            The key ``figures/{document_id}/{element_id}.png``.
        """
        return f"figures/{document_id}/{element_id}.png"

    @staticmethod
    def page_image_key_for(*, document_id: uuid.UUID, page_number: int) -> str:
        """Return the storage key of the rendered image of a document page.

        Args:
            document_id: Document the page belongs to.
            page_number: 1-based page number.

        Returns:
            The key ``pages/{document_id}/{page_number}.png``.
        """
        return f"pages/{document_id}/{page_number}.png"

    def with_image_key(self, image_key: str) -> ExtractedElement:
        """Return the image with the storage key of its crop.

        Args:
            image_key: Key under which the crop is stored.

        Returns:
            A copy of the element that references its crop.

        Raises:
            InvalidElementError: If the element is not an image.
        """
        if self.kind is not ElementKind.IMAGE:
            raise InvalidElementError(f"Element {self.id} is not an image")
        return replace(self, image_key=image_key)

    def as_decorative(self) -> ExtractedElement:
        """Return the image flagged as a logo, stamp or repeated decoration.

        Returns:
            A copy of the element with ``is_decorative`` set.

        Raises:
            InvalidElementError: If the element is not an image.
        """
        if self.kind is not ElementKind.IMAGE:
            raise InvalidElementError(f"Element {self.id} is not an image")
        return replace(self, is_decorative=True)

    def with_description(
        self,
        *,
        status: DescriptionStatus,
        description: str | None = None,
        unverified_identifiers: tuple[str, ...] = (),
    ) -> ExtractedElement:
        """Return the image with the outcome of its description.

        Args:
            status: Outcome of the description.
            description: Generated text, required when ``status`` is ``described``.
            unverified_identifiers: Identifiers not found in labels or caption.

        Returns:
            A copy of the element with the description fields set.

        Raises:
            InvalidElementError: If the element is not an image or a described status
                has no text.
        """
        if self.kind is not ElementKind.IMAGE:
            raise InvalidElementError(f"Element {self.id} is not an image")
        if (status is DescriptionStatus.DESCRIBED) != bool(description):
            raise InvalidElementError(
                f"Element {self.id}: description text is required only when described"
            )
        return replace(
            self,
            description=description,
            description_status=status,
            unverified_identifiers=unverified_identifiers,
        )


@dataclass(frozen=True, slots=True)
class ElementRelationship:
    """Link between two extracted elements.

    Attributes:
        source_id: Element the link starts from, such as a caption.
        target_id: Element the link points to, such as an image.
        kind: Meaning of the link.
        score: Proximity or match strength, for ``near`` and ``continues``.
    """

    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: RelationshipKind
    score: float | None = None

    def __post_init__(self) -> None:
        """Reject self-links."""
        if self.source_id == self.target_id:
            raise InvalidElementError(f"Element {self.source_id} cannot link to itself")


@dataclass(frozen=True, slots=True)
class PagedBox:
    """A bounding box together with its page number.

    Attributes:
        page: 1-based page number.
        bbox: Position on the page.
    """

    page: int
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class RetrievalUnit:
    """A structurally coherent group of content prepared for search.

    Attributes:
        id: Deterministic id, see ``unit_id_for``.
        document_id: Document the unit belongs to.
        unit_type: Text, table or figure unit.
        text: Content of the unit, shown to readers. ``embedding_text`` adds the
            heading path for the vectors.
        heading_path: Section headings in scope, outermost first.
        pages: Pages the unit spans, in ascending order.
        element_ids: Source elements.
        boxes: Positions of the source elements.
        figure_ids: Related images.
        image_key: Storage key of the crop, for figure units.
    """

    id: uuid.UUID
    document_id: uuid.UUID
    unit_type: UnitType
    text: str
    heading_path: tuple[str, ...]
    pages: tuple[int, ...]
    element_ids: tuple[uuid.UUID, ...]
    boxes: tuple[PagedBox, ...]
    figure_ids: tuple[uuid.UUID, ...] = ()
    image_key: str | None = None

    @property
    def embedding_text(self) -> str:
        """Heading path and text joined by newlines, as embedded and fed to BM25."""
        return "\n".join((*self.heading_path, self.text))
