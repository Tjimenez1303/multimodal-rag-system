"""Request and response bodies of the REST API, as declared in the OpenAPI contracts."""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from multimodal_rag.answering.domain import (
    Answer,
    AnswerImage,
    AnswerStatus,
    Citation,
    NotEnoughReason,
    RetrievedSource,
    TableContent,
)
from multimodal_rag.ingestion.domain import (
    DescriptionStatus,
    ElementKind,
    FailureCode,
    JobStage,
    JobStatus,
    RelationshipKind,
    TextOrigin,
    UnitType,
)
from multimodal_rag.ingestion.use_cases.intake import Submission
from multimodal_rag.ingestion.use_cases.library import DocumentView, ElementView


# Bodies of the upload and job routes
class UploadAccepted(BaseModel):
    """Identifiers returned by an upload.

    Attributes:
        document_id: Document registered for the file's content.
        job_id: Job that ingests the document.
        status: Current state of that job.
        already_ingested: Whether identical content had already completed.
    """

    document_id: uuid.UUID
    job_id: uuid.UUID
    status: JobStatus
    already_ingested: bool

    @classmethod
    def from_submission(cls, submission: Submission) -> Self:
        """Build the body from the outcome of an upload.

        Args:
            submission: Result of ``SubmitDocument``.

        Returns:
            The response body.
        """
        return cls(
            document_id=submission.document.id,
            job_id=submission.job.id,
            status=submission.job.status,
            already_ingested=submission.already_ingested,
        )


class JobSummaryBody(BaseModel):
    """Counts of what a completed job captured.

    Attributes:
        pages: Pages processed.
        text_elements: Headings, paragraphs, list items and captions.
        tables: Table elements.
        table_chains: Tables that continue across pages.
        images: Image elements.
        figures_described: Images with a generated description.
        figures_skipped: Images not sent to the vision model.
        figures_not_described: Images whose description failed.
        retrieval_units: Units written to the index.
        recognized_pages: Pages that went through text recognition.
    """

    model_config = ConfigDict(from_attributes=True)

    pages: int
    text_elements: int
    tables: int
    table_chains: int
    images: int
    figures_described: int
    figures_skipped: int
    figures_not_described: int
    retrieval_units: int
    recognized_pages: int


class JobBody(BaseModel):
    """State and progress of an ingestion job.

    Built from a domain job with ``model_validate(job)``, which reads only the
    declared fields, so lease and worker details never reach clients.

    Attributes:
        id: Job id.
        document_id: Document being ingested.
        status: Lifecycle state.
        stage: Current step while processing.
        attempt: Attempts started so far.
        max_attempts: Attempts allowed.
        pages_done: Pages processed in the current attempt.
        pages_total: Pages to process, once known.
        failure_code: Cause of a failure.
        failure_reason: Human-readable failure reason.
        summary: Counts of a completed job.
        created_at: Creation time.
        started_at: Time of the first claim.
        finished_at: Time the job completed or failed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    status: JobStatus
    stage: JobStage | None
    attempt: int
    max_attempts: int
    pages_done: int
    pages_total: int | None
    failure_code: FailureCode | None
    failure_reason: str | None
    summary: JobSummaryBody | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# Bodies of the document library routes
class DocumentBody(BaseModel):
    """A document of the library with its newest job.

    Attributes:
        id: Document id.
        file_name: Name of the uploaded file.
        size_bytes: Size of the file.
        page_count: Page count, unknown for encrypted files.
        created_at: Time the document was registered.
        latest_job: Newest job, or ``None`` until its job is enqueued.
    """

    id: uuid.UUID
    file_name: str
    size_bytes: int
    page_count: int | None
    created_at: datetime
    latest_job: JobBody | None

    @classmethod
    def from_view(cls, view: DocumentView) -> Self:
        """Build the body of a document.

        Args:
            view: Document and its latest job.

        Returns:
            The response body.
        """
        # Flatten the document and its latest job into one body
        document = view.document
        job = view.latest_job
        return cls(
            id=document.id,
            file_name=document.file_name,
            size_bytes=document.size_bytes,
            page_count=document.page_count,
            created_at=document.created_at,
            latest_job=None if job is None else JobBody.model_validate(job),
        )


class DocumentPageBody(BaseModel):
    """One page of documents, newest first.

    Attributes:
        items: Documents of this page.
        next_cursor: Cursor of the next page, or ``None`` on the last page.
    """

    items: list[DocumentBody]
    next_cursor: str | None


# Bodies of the element listing route
class BoundingBoxBody(BaseModel):
    """Position on a page in PDF points with a top-left origin.

    Attributes:
        left: Distance from the left edge of the page.
        top: Distance from the top edge of the page.
        right: Distance from the left edge to the right side of the box.
        bottom: Distance from the top edge to the bottom side of the box.
        origin: Always ``top_left``.
    """

    left: float
    top: float
    right: float
    bottom: float
    origin: Literal["top_left"] = "top_left"


class TableBody(BaseModel):
    """Rows and columns of a table.

    Attributes:
        rows: Number of rows, the header included.
        columns: Number of columns.
        cells: Cell text, row by row.
    """

    rows: int
    columns: int
    cells: list[list[str]]


class RelationshipBody(BaseModel):
    """A directed link between two elements.

    Attributes:
        source_id: Element the link starts from, such as a caption.
        target_id: Element the link points to, such as an image.
        kind: Meaning of the link.
    """

    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: RelationshipKind


class ElementBody(BaseModel):
    """A captured element with its position and relationships.

    Attributes:
        id: Element id.
        kind: Type of content.
        page: 1-based page number.
        bbox: Position on the page.
        reading_order: Order within the document.
        heading_level: Level of a heading.
        text: Text content, or the Markdown of a table.
        table: Rows and columns of a table.
        origin: Whether the text came from the text layer or from recognition.
        confidence: Recognition confidence of recognized text.
        image_url: Relative URL of the stored crop of an image.
        image_class: Classifier label of an image.
        labels: Text printed inside an image.
        description: Generated description of an image.
        description_status: Outcome of describing an image.
        unverified_identifiers: Identifiers of the description absent from the
            image's labels and caption.
        is_decorative: Whether the image is a logo or a repeated decoration.
        relationships: Every link that touches the element.
    """

    id: uuid.UUID
    kind: ElementKind
    page: int
    bbox: BoundingBoxBody
    reading_order: int
    heading_level: int | None
    text: str | None
    table: TableBody | None
    origin: TextOrigin
    confidence: float | None
    image_url: str | None
    image_class: str | None
    labels: list[str]
    description: str | None
    description_status: DescriptionStatus | None
    unverified_identifiers: list[str]
    is_decorative: bool
    relationships: list[RelationshipBody]

    @classmethod
    def from_view(cls, view: ElementView, *, image_url: str | None) -> Self:
        """Build the body of an element.

        Args:
            view: Element and its relationships.
            image_url: Relative URL of its crop, for images with one.

        Returns:
            The response body.
        """
        # Copy the element's fields, box, table rows and relationships
        element = view.element
        box = element.bbox
        table = element.table
        return cls(
            id=element.id,
            kind=element.kind,
            page=element.page,
            bbox=BoundingBoxBody(
                left=box.left, top=box.top, right=box.right, bottom=box.bottom
            ),
            reading_order=element.reading_order,
            heading_level=element.heading_level,
            text=element.text,
            table=None
            if table is None
            else TableBody(
                rows=len(table),
                columns=max((len(row) for row in table), default=0),
                cells=[list(row) for row in table],
            ),
            origin=element.origin,
            confidence=element.confidence,
            image_url=image_url,
            image_class=element.image_class,
            labels=list(element.labels),
            description=element.description,
            description_status=element.description_status,
            unverified_identifiers=list(element.unverified_identifiers),
            is_decorative=element.is_decorative,
            relationships=[
                RelationshipBody(
                    source_id=link.source_id, target_id=link.target_id, kind=link.kind
                )
                for link in view.relationships
            ],
        )


class ElementPageBody(BaseModel):
    """One page of elements in reading order.

    Attributes:
        items: Elements of this page.
        next_cursor: Cursor of the next page, or ``None`` on the last page.
    """

    items: list[ElementBody]
    next_cursor: str | None


# Bodies of the question route
class QuestionBody(BaseModel):
    """A question about the ingested documents.

    The length of the question is not limited here: the use case enforces the
    configurable limit and answers ``invalid_question``.

    Attributes:
        question: The question, in any language.
    """

    model_config = ConfigDict(extra="forbid")

    question: str


class CitationBody(BaseModel):
    """A numbered citation of the answer.

    Attributes:
        number: Number of the ``[n]`` markers that refer to it.
        document_id: Cited document.
        document_name: File name of the cited document.
        pages: Cited pages, ascending.
        unit_ids: Retrieval units behind the citation.
    """

    number: int
    document_id: uuid.UUID
    document_name: str
    pages: list[int]
    unit_ids: list[uuid.UUID]

    @classmethod
    def from_citation(cls, citation: Citation) -> Self:
        """Build the body of a citation.

        Args:
            citation: Citation of the answer.

        Returns:
            The response body.
        """
        return cls(
            number=citation.number,
            document_id=citation.document_id,
            document_name=citation.document_name,
            pages=list(citation.pages),
            unit_ids=list(citation.unit_ids),
        )


class TableContentBody(BaseModel):
    """Rows of one part of a table.

    Attributes:
        page: Page of this part.
        rows: Cell text, header row first.
    """

    page: int
    rows: list[list[str]]

    @classmethod
    def from_table(cls, table: TableContent) -> Self:
        """Build the body of a table part.

        Args:
            table: Rows of a table part.

        Returns:
            The response body.
        """
        return cls(page=table.page, rows=[list(row) for row in table.rows])


class SourceBody(BaseModel):
    """A retrieval unit supplied to the answer model.

    Attributes:
        unit_id: Retrieval unit id.
        rank: Position in judged order, which is the order supplied to the answer
            model.
        relevance: The reranker's probability that the unit contains the
            information that answers the question.
        similarity: Dense cosine similarity to the question. Informational, it does
            not gate.
        document_id: Document of the unit.
        document_name: File name of that document.
        section: Heading path, outermost first.
        pages: Pages the unit spans.
        content_type: Text, table or figure unit.
        excerpt: Beginning of the unit text.
        cited: Whether the answer cites the unit.
        citation_number: Citation that cites the unit.
        low_confidence_text: Part of the content was recognized with low confidence.
        generated_description: The content includes a figure description written by
            a model.
        unverified_identifiers: Identifiers of that description missing from the
            figure's labels and caption.
        tables: Rows of each part of a table unit.
        figure_ids: Non-decorative image elements associated with the unit.
    """

    unit_id: uuid.UUID
    rank: int
    relevance: float = Field(ge=0, le=1)
    similarity: float
    document_id: uuid.UUID
    document_name: str
    section: list[str]
    pages: list[int]
    content_type: UnitType
    excerpt: str
    cited: bool
    citation_number: int | None
    low_confidence_text: bool
    generated_description: bool
    unverified_identifiers: list[str]
    tables: list[TableContentBody]
    figure_ids: list[uuid.UUID]

    @classmethod
    def from_source(cls, source: RetrievedSource) -> Self:
        """Build the body of a retrieved source.

        Args:
            source: Source supplied to the answer model.

        Returns:
            The response body.
        """
        return cls(
            unit_id=source.unit_id,
            rank=source.rank,
            relevance=source.relevance,
            similarity=source.similarity,
            document_id=source.document_id,
            document_name=source.document_name,
            section=list(source.section),
            pages=list(source.pages),
            content_type=source.content_type,
            excerpt=source.excerpt,
            cited=source.citation_number is not None,
            citation_number=source.citation_number,
            low_confidence_text=source.low_confidence_text,
            generated_description=source.generated_description,
            unverified_identifiers=list(source.unverified_identifiers),
            tables=[TableContentBody.from_table(table) for table in source.tables],
            figure_ids=list(source.figure_ids),
        )


class AnswerImageBody(BaseModel):
    """A figure returned with an answer.

    Attributes:
        element_id: Image element id.
        document_id: Document of the figure.
        document_name: File name of that document.
        page: Page of the figure.
        bbox: Position of the figure on the page.
        caption: Caption of the figure, if any.
        unit_id: Cited unit that brought the figure.
        url: Path of the PNG, served by the document image route.
    """

    element_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page: int
    bbox: BoundingBoxBody
    caption: str | None
    unit_id: uuid.UUID
    url: str

    @classmethod
    def from_image(cls, image: AnswerImage, *, url: str) -> Self:
        """Build the body of an answer image.

        Args:
            image: Figure selected for the answer.
            url: Path of its PNG.

        Returns:
            The response body.
        """
        box = image.bbox
        return cls(
            element_id=image.element_id,
            document_id=image.document_id,
            document_name=image.document_name,
            page=image.page,
            bbox=BoundingBoxBody(
                left=box.left, top=box.top, right=box.right, bottom=box.bottom
            ),
            caption=image.caption,
            unit_id=image.unit_id,
            url=url,
        )


class AnswerBody(BaseModel):
    """The answer to a question.

    Attributes:
        status: ``answered`` or ``not_enough_information``.
        reason: Why there is no answer, only when not answered.
        answer: Markdown with ``[n]`` markers, or the not-enough message.
        not_covered: What the documents do not answer, for a partial answer.
        citations: Numbered citations.
        sources: Every unit supplied to the answer model, in rank order.
        primary_image: The figure closest to the most relevant cited text.
        related_images: Other figures of the cited units.
    """

    status: AnswerStatus
    reason: NotEnoughReason | None
    answer: str
    not_covered: str | None
    citations: list[CitationBody]
    sources: list[SourceBody]
    primary_image: AnswerImageBody | None
    related_images: list[AnswerImageBody]

    @classmethod
    def from_answer(
        cls, answer: Answer, *, image_url: Callable[[AnswerImage], str]
    ) -> Self:
        """Build the body of an answer.

        Args:
            answer: Outcome of the question.
            image_url: Path of the PNG of an answer image.

        Returns:
            The response body.
        """
        # Serialize the answer, giving every image the URL of its crop
        primary = answer.primary_image
        return cls(
            status=answer.status,
            reason=answer.reason,
            answer=answer.text,
            not_covered=answer.not_covered,
            citations=[CitationBody.from_citation(c) for c in answer.citations],
            sources=[SourceBody.from_source(source) for source in answer.sources],
            primary_image=None
            if primary is None
            else AnswerImageBody.from_image(primary, url=image_url(primary)),
            related_images=[
                AnswerImageBody.from_image(image, url=image_url(image))
                for image in answer.related_images
            ],
        )
