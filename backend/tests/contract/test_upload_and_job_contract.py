import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.body_limit import (
    MULTIPART_OVERHEAD_BYTES,
    BodyLimits,
)
from multimodal_rag.adapters.http.dependencies import (
    provide_get_job,
    provide_submit_document,
)
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_ingestion import ingestion_router
from multimodal_rag.ingestion.domain import JobStage
from multimodal_rag.ingestion.use_cases.intake import (
    GetJob,
    SubmitDocument,
    UploadLimits,
)
from tests.contract.contract import HttpResponse, assert_matches_contract
from tests.fakes import (
    FakePdfInspector,
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryJobQueue,
    claim_next,
    finish_next,
)

UPLOADS = "/api/v1/documents"
JOB = "/api/v1/jobs/{job_id}"
MAX_BYTES = 4_096
PDF = b"%PDF-1.7\n" + b"%" * 1_000


@dataclass
class Api:
    client: TestClient
    jobs: InMemoryJobQueue
    blobs: InMemoryBlobStorage
    inspector: FakePdfInspector

    def upload(self, data: bytes = PDF, name: str = "manual.pdf") -> HttpResponse:
        return self.client.post(
            UPLOADS, files={"file": (name, data, "application/pdf")}
        )


@pytest.fixture
def api() -> Iterator[Api]:
    clock = FrozenClock()
    jobs = InMemoryJobQueue(clock)
    blobs = InMemoryBlobStorage()
    inspector = FakePdfInspector(page_count=12)
    submit = SubmitDocument(
        documents=InMemoryDocumentRepository(),
        jobs=jobs,
        blobs=blobs,
        inspector=inspector,
        clock=clock,
        limits=UploadLimits(max_bytes=MAX_BYTES, max_pages=500),
        max_attempts=3,
    )
    app = create_app(
        readiness_checks={},
        routers=(ingestion_router,),
        body_limits=BodyLimits(by_path={UPLOADS: MAX_BYTES + MULTIPART_OVERHEAD_BYTES}),
    )
    app.dependency_overrides[provide_submit_document] = lambda: submit
    app.dependency_overrides[provide_get_job] = lambda: GetJob(jobs=jobs)
    with TestClient(RequestContextMiddleware(app)) as client:
        yield Api(client, jobs, blobs, inspector)


def test_new_upload_is_accepted_with_a_pending_job(api: Api) -> None:
    response = api.client.post(
        UPLOADS,
        files={"file": ("manual.pdf", PDF, "application/pdf")},
        headers={"X-Request-ID": "upload-1"},
    )

    assert response.status_code == 202
    assert_matches_contract(response, path=UPLOADS, method="post")
    body = response.json()
    assert body["status"] == "pending"
    assert body["already_ingested"] is False
    assert response.headers["location"] == f"/api/v1/jobs/{body['job_id']}"
    job = next(iter(api.jobs.jobs.values()))
    assert job.correlation_id == "upload-1"


def test_identical_upload_in_progress_returns_the_same_job(api: Api) -> None:
    first = api.upload().json()

    second = api.upload()

    assert second.status_code == 202
    assert second.json() == first


async def test_identical_upload_already_completed_returns_200(api: Api) -> None:
    first = api.upload().json()
    await finish_next(api.jobs, succeed=True)

    second = api.upload()

    assert second.status_code == 200
    assert_matches_contract(second, path=UPLOADS, method="post")
    assert second.json() == first | {"status": "completed", "already_ingested": True}


async def test_identical_upload_after_a_failure_gets_a_new_job(api: Api) -> None:
    first = api.upload().json()
    await finish_next(api.jobs, succeed=False)

    second = api.upload()

    assert second.status_code == 202
    assert second.json()["job_id"] != first["job_id"]
    assert second.json()["document_id"] == first["document_id"]


@pytest.mark.parametrize(
    ("data", "name", "status", "code"),
    [
        (b"plain text", "manual.pdf", 415, "unsupported_media_type"),
        (PDF + b"%" * MAX_BYTES, "manual.pdf", 413, "file_too_large"),
        (PDF, "x" * 300 + ".pdf", 400, "invalid_file_name"),
    ],
)
def test_rejected_uploads_are_problem_details_without_a_job(
    api: Api, data: bytes, name: str, status: int, code: str
) -> None:
    response = api.upload(data, name)

    assert response.status_code == status
    assert_matches_contract(response, path=UPLOADS, method="post")
    assert response.json()["code"] == code
    assert api.jobs.jobs == {}
    assert api.blobs.blobs == {}


def test_too_many_pages_is_unprocessable(api: Api) -> None:
    api.inspector.page_count = 501

    response = api.upload()

    assert response.status_code == 422
    assert_matches_contract(response, path=UPLOADS, method="post")
    assert response.json()["code"] == "page_limit_exceeded"


def test_missing_file_field_is_a_bad_request(api: Api) -> None:
    response = api.client.post(UPLOADS, data={"other": "x"})

    assert response.status_code == 400
    assert_matches_contract(response, path=UPLOADS, method="post")
    assert response.json()["code"] == "invalid_request"


def test_declared_oversize_body_is_rejected_before_it_is_read(api: Api) -> None:
    oversized = MAX_BYTES + MULTIPART_OVERHEAD_BYTES + 1

    response = api.client.post(
        UPLOADS,
        content=b"x" * 16,
        headers={
            "content-type": "multipart/form-data; boundary=b",
            "content-length": str(oversized),
        },
    )

    assert response.status_code == 413
    assert_matches_contract(response, path=UPLOADS, method="post")
    assert response.json()["code"] == "file_too_large"


def test_undeclared_oversize_body_is_rejected_while_it_streams(api: Api) -> None:
    # The file itself is within the limit, so only the middleware counting the
    # streamed bytes can refuse this body.
    padding = b"x" * (MAX_BYTES + MULTIPART_OVERHEAD_BYTES)

    def chunks() -> Iterator[bytes]:
        yield b'--b\r\nContent-Disposition: form-data; name="note"\r\n\r\n'
        yield padding
        yield b'\r\n--b\r\nContent-Disposition: form-data; name="file"; '
        yield b'filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        yield PDF
        yield b"\r\n--b--\r\n"

    response = api.client.post(
        UPLOADS,
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )

    assert response.status_code == 413
    assert_matches_contract(response, path=UPLOADS, method="post")
    assert response.json()["code"] == "file_too_large"
    assert api.jobs.jobs == {}


def test_location_includes_the_root_path_of_a_mounted_api(api: Api) -> None:
    mounted = TestClient(api.client.app, root_path="/rag")

    response = mounted.post(UPLOADS, files={"file": ("a.pdf", PDF, "application/pdf")})

    assert response.headers["location"].startswith("/rag/api/v1/jobs/")


def test_pending_job_matches_the_contract(api: Api) -> None:
    job_id = api.upload().json()["job_id"]

    response = api.client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert_matches_contract(response, path=JOB, method="get")
    assert response.json()["status"] == "pending"
    assert response.json()["attempt"] == 0


async def test_processing_job_reports_stage_and_pages(api: Api) -> None:
    job_id = api.upload().json()["job_id"]
    job = await claim_next(api.jobs)
    assert job.lease_token is not None
    await api.jobs.update_progress(
        job_id=job.id,
        lease_token=job.lease_token,
        stage=JobStage.EXTRACTING,
        pages_done=4,
        pages_total=12,
    )

    response = api.client.get(f"/api/v1/jobs/{job_id}")

    assert_matches_contract(response, path=JOB, method="get")
    body = response.json()
    assert (body["status"], body["stage"]) == ("processing", "extracting")
    assert (body["pages_done"], body["pages_total"]) == (4, 12)


@pytest.mark.parametrize("succeed", [True, False])
async def test_finished_jobs_match_the_contract(api: Api, succeed: bool) -> None:
    job_id = api.upload().json()["job_id"]
    await finish_next(api.jobs, succeed=succeed)

    response = api.client.get(f"/api/v1/jobs/{job_id}")

    assert_matches_contract(response, path=JOB, method="get")
    body = response.json()
    if succeed:
        assert body["summary"]["pages"] == 12
        assert body["failure_reason"] is None
    else:
        assert body["failure_code"] == "encrypted_document"
        assert body["summary"] is None


def test_unknown_job_is_not_found(api: Api) -> None:
    response = api.client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert_matches_contract(response, path=JOB, method="get")
    assert response.json()["code"] == "job_not_found"


def test_malformed_job_id_is_a_bad_request(api: Api) -> None:
    response = api.client.get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 400
    assert_matches_contract(response, path=JOB, method="get")
