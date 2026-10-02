"""Routes that accept uploads and report the progress of their jobs."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response, UploadFile

from multimodal_rag.adapters.http.dependencies import (
    GetJobDep,
    RequestIdDep,
    SubmitDocumentDep,
)
from multimodal_rag.adapters.http.problems import problem_responses
from multimodal_rag.adapters.http.schemas import JobBody, UploadAccepted

# Size of each read from the spooled upload while it is streamed to storage.
UPLOAD_CHUNK_BYTES = 1024 * 1024

# Response header that points to the job's status URL
_LOCATION: dict[str, Any] = {
    "Location": {
        "description": "Status URL of the job",
        "schema": {"type": "string"},
    }
}

API_PREFIX = "/api/v1"
UPLOAD_PATH = f"{API_PREFIX}/documents"
# The request context middleware reads this header, the contract documents it here.
REQUEST_ID_PARAMETER = {
    "name": "X-Request-ID",
    "in": "header",
    "required": False,
    "schema": {"type": "string", "maxLength": 128},
}

ingestion_router = APIRouter(prefix=API_PREFIX, tags=["ingestion"])


@ingestion_router.post(
    "/documents",
    operation_id="uploadDocument",
    description=(
        "Stores the file, registers the document by the SHA-256 of its bytes and "
        "enqueues an ingestion job. Answers 202 while the job is pending or "
        "processing, and 200 when identical content already completed."
    ),
    status_code=202,
    openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    responses={
        202: {"description": "Job pending or processing", "headers": _LOCATION},
        200: {
            "model": UploadAccepted,
            "description": "Identical content already ingested",
            "headers": _LOCATION,
        },
        **problem_responses(400, 413, 415, 422),
    },
)
async def upload_document(
    file: UploadFile,
    submit: SubmitDocumentDep,
    request_id: RequestIdDep,
    request: Request,
    response: Response,
) -> UploadAccepted:
    """Store a PDF and enqueue its ingestion without processing it.

    Args:
        file: The uploaded PDF, spooled by Starlette.
        submit: Upload use case.
        request_id: Correlation id stored on a new job.
        request: Request being handled, used to build the job URL.
        response: Response whose status and headers are set here.

    Returns:
        The document and job identifiers.
    """
    # Hand the streamed file to the upload use case
    submission = await submit(
        file_name=file.filename or "", content=_chunks(file), correlation_id=request_id
    )

    # 200 when the same content was already ingested, 202 while a job runs
    response.status_code = 200 if submission.already_ingested else 202

    # Point the client to the status URL of the job
    response.headers["Location"] = request.url_for(
        "get_job", job_id=str(submission.job.id)
    ).path
    return UploadAccepted.from_submission(submission)


@ingestion_router.get(
    "/jobs/{job_id}",
    operation_id="getJob",
    description="State, stage and page progress of an ingestion job.",
    responses=problem_responses(400, 404),
)
async def get_job(job_id: uuid.UUID, find_job: GetJobDep) -> JobBody:
    """Return the state, stage and page progress of an ingestion job.

    Args:
        job_id: Id returned by the upload.
        find_job: Job status use case.

    Returns:
        The job without lease or worker details.
    """
    # Load the job and serialize it as the response body
    return JobBody.model_validate(await find_job(job_id))


async def _chunks(file: UploadFile) -> AsyncIterator[bytes]:
    # UploadFile.read runs in a thread once the upload is spooled to disk.
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        yield chunk
