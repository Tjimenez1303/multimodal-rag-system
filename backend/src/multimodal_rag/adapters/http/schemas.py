"""Response bodies of the REST API, as declared in the OpenAPI contract."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict

from multimodal_rag.ingestion.domain import FailureCode, JobStage, JobStatus
from multimodal_rag.ingestion.use_cases.intake import Submission


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
