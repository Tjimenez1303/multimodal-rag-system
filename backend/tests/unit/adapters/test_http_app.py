import asyncio
import io
import json
import logging
import time
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.body_limit import BodyLimits, BodySizeLimitMiddleware
from multimodal_rag.adapters.http.dependencies import RequestIdDep
from multimodal_rag.adapters.http.problems import (
    PROBLEM_CODE_PATTERN,
    http_problem_code,
    status_for,
)
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.ingestion.errors import (
    FileTooLargeError,
    JobNotFoundError,
    PageLimitExceededError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
    MultimodalRagError,
    ProviderUnavailableError,
    StorageError,
)
from multimodal_rag.shared.logging import configure_logging

probe_router = APIRouter()


@probe_router.get("/probe/not-found")
async def raise_not_found() -> None:
    raise JobNotFoundError("Job 42 not found")


@probe_router.get("/probe/inconsistent")
async def raise_inconsistency() -> None:
    raise DataInconsistencyError("element 7 has no page, secret-path=/data/x")


@probe_router.get("/probe/crash")
async def crash() -> None:
    raise RuntimeError("unexpected")


@probe_router.get("/probe/request-id")
async def echo_request_id(request_id: RequestIdDep) -> dict[str, str]:
    return {"request_id": request_id}


@probe_router.post("/probe/upload")
async def accept_upload() -> dict[str, str]:
    return {"status": "stored"}


@probe_router.get("/probe/items/{item_id}")
async def typed(item_id: int) -> dict[str, int]:
    return {"item_id": item_id}


async def healthy() -> None:
    return None


async def broken() -> None:
    raise ConnectionRefusedError("database down")


async def hanging() -> None:
    await asyncio.sleep(10)


def served(app: FastAPI) -> RequestContextMiddleware:
    """Wrap the app the way the composition root serves it."""
    return RequestContextMiddleware(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        readiness_checks={"database": healthy, "blob_storage": healthy},
        routers=(probe_router,),
    )
    with TestClient(served(app), raise_server_exceptions=False) as test_client:
        yield test_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_lists_passing_checks(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": ["blob_storage", "database"],
    }


def test_readiness_reports_failing_dependencies() -> None:
    app = create_app(readiness_checks={"database": broken, "blob_storage": healthy})

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "not_ready"
    assert response.json()["detail"] == "Unavailable: database"


def test_generated_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health/live")

    assert len(response.headers["x-request-id"]) == 32


def test_safe_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "upload-123"})

    assert response.headers["x-request-id"] == "upload-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id\x7f"})

    assert response.headers["x-request-id"] != "bad id\x7f"


def test_domain_errors_become_problem_details(client: TestClient) -> None:
    response = client.get("/probe/not-found", headers={"X-Request-ID": "req-9"})

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "code": "job_not_found",
        "instance": "/probe/not-found",
        "request_id": "req-9",
        "detail": "Job 42 not found",
    }


def test_internal_errors_hide_their_details(client: TestClient) -> None:
    response = client.get("/probe/inconsistent")

    assert response.status_code == 500
    assert response.json()["code"] == "data_inconsistency"
    assert "detail" not in response.json()


def test_unexpected_errors_become_internal_errors(client: TestClient) -> None:
    response = client.get("/probe/crash")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


def test_invalid_parameters_become_bad_requests(client: TestClient) -> None:
    response = client.get("/probe/items/not-a-number")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert "item_id" in response.json()["detail"]


def test_unknown_routes_are_problem_details(client: TestClient) -> None:
    response = client.get("/nowhere")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (UnsupportedMediaTypeError("x"), 415),
        (FileTooLargeError("x"), 413),
        (PageLimitExceededError("x"), 422),
        (ProviderUnavailableError("x"), 503),
        (StorageError("x"), 503),
        (MultimodalRagError("x"), 500),
    ],
)
def test_status_mapping_uses_the_most_specific_class(
    error: MultimodalRagError, status: int
) -> None:
    assert status_for(error) == status


def test_unhandled_errors_carry_the_request_id_in_header_and_logs() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", stream=stream)
    app = create_app(readiness_checks={}, routers=(probe_router,))

    with TestClient(served(app), raise_server_exceptions=False) as client:
        response = client.get("/probe/crash", headers={"X-Request-ID": "crash-1"})
    logging.getLogger().handlers = []

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "crash-1"
    assert response.json()["request_id"] == "crash-1"
    errors = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert any(
        record["level"] == "error" and record["request_id"] == "crash-1"
        for record in errors
    )


def test_readiness_gives_up_on_a_hanging_probe() -> None:
    app = create_app(
        readiness_checks={"database": hanging}, readiness_timeout_seconds=0.05
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Unavailable: database"


def test_plain_http_errors_use_status_phrase_codes(client: TestClient) -> None:
    response = client.post("/health/live")

    assert response.status_code == 405
    # RFC 9110 section 15.5.6: a 405 must list the methods the resource allows.
    assert response.headers["allow"] == "GET"
    assert response.json()["code"] == "method_not_allowed"
    assert response.json()["title"] == "Method Not Allowed"


def test_http_problem_codes_drop_punctuation() -> None:
    assert http_problem_code(418) == "i_m_a_teapot"


def test_every_error_code_is_unique_lowercase_snake_case() -> None:
    pending: list[type[MultimodalRagError]] = [MultimodalRagError]
    codes: list[str] = []
    while pending:
        error_class = pending.pop()
        codes.append(error_class.code)
        pending.extend(error_class.__subclasses__())

    assert [c for c in codes if not PROBLEM_CODE_PATTERN.fullmatch(c)] == []
    assert len(codes) == len(set(codes))


def test_the_app_keeps_fastapi_features_for_callers() -> None:
    app = create_app(readiness_checks={})

    assert isinstance(app, FastAPI)
    assert "/health/ready" in app.openapi()["paths"]
    assert all("/problems" not in path for path in app.openapi()["paths"])


def request_lines(stream: io.StringIO) -> list[dict[str, object]]:
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [record for record in records if record["message"] == "request completed"]


@pytest.fixture
def logged_client() -> Iterator[tuple[TestClient, io.StringIO]]:
    stream = io.StringIO()
    configure_logging(log_format="json", level="DEBUG", stream=stream)
    app = create_app(readiness_checks={"database": healthy}, routers=(probe_router,))
    with TestClient(served(app), raise_server_exceptions=False) as client:
        yield client, stream
    logging.getLogger().handlers = []


def test_each_request_logs_one_line_with_the_route_template(
    logged_client: tuple[TestClient, io.StringIO],
) -> None:
    client, stream = logged_client

    client.get("/probe/items/7?token=secret", headers={"X-Request-ID": "line-1"})

    [line] = request_lines(stream)
    assert line["http.request.method"] == "GET"
    assert line["http.route"] == "/probe/items/{item_id}"
    assert line["http.response.status_code"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == "line-1"
    assert line["level"] == "info"
    app_records = [
        line
        for line in stream.getvalue().splitlines()
        if json.loads(line)["logger"].startswith("multimodal_rag")
    ]
    assert app_records
    assert all("secret" not in record for record in app_records)


def test_failed_requests_are_logged_with_their_status(
    logged_client: tuple[TestClient, io.StringIO],
) -> None:
    client, stream = logged_client

    client.get("/probe/crash")

    [line] = request_lines(stream)
    assert line["http.response.status_code"] == 500
    assert line["http.route"] == "/probe/crash"


def test_unmatched_paths_are_logged_without_a_route(
    logged_client: tuple[TestClient, io.StringIO],
) -> None:
    client, stream = logged_client

    client.get("/nowhere/123")

    [line] = request_lines(stream)
    assert line["http.response.status_code"] == 404
    assert "http.route" not in line


def test_health_probes_are_logged_below_info(
    logged_client: tuple[TestClient, io.StringIO],
) -> None:
    client, stream = logged_client

    client.get("/health/ready")

    [line] = request_lines(stream)
    assert line["level"] == "debug"


def test_readiness_probes_run_concurrently() -> None:
    app = create_app(
        readiness_checks={"database": hanging, "blob_storage": hanging},
        readiness_timeout_seconds=0.3,
    )

    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.get("/health/ready")
        elapsed = time.perf_counter() - started

    assert response.json()["detail"] == "Unavailable: blob_storage, database"
    assert elapsed < 0.55


async def test_a_content_length_that_is_not_ascii_digits_is_ignored() -> None:
    reached: list[bool] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(True)

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        return None

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", "\u00b2".encode("latin-1"))],
    }
    limits = BodyLimits(default_bytes=10)
    await BodySizeLimitMiddleware(app, limits=limits)(scope, receive, send)

    assert reached == [True]


def test_an_upload_route_works_without_the_request_id_middleware() -> None:
    app = create_app(readiness_checks={}, routers=(probe_router,))

    with TestClient(app) as client:
        response = client.get("/probe/request-id")

    assert response.status_code == 200
    assert len(response.json()["request_id"]) == 32


def test_an_unexpected_error_is_answered_once_and_not_raised_again() -> None:
    # The problem handler already logged it with the request id, so re-raising
    # would make the server log the same traceback a second time.
    app = create_app(readiness_checks={}, routers=(probe_router,))

    with TestClient(served(app)) as client:
        response = client.get("/probe/crash")

    assert response.status_code == 500


def test_routes_without_their_own_limit_get_the_default_body_limit() -> None:
    app = create_app(
        readiness_checks={},
        routers=(probe_router,),
        body_limits=BodyLimits(default_bytes=10, by_path={"/probe/upload": 1_000}),
    )

    with TestClient(served(app)) as client:
        small_route = client.post("/probe/items/1", content=b"x" * 100)
        upload_route = client.post("/probe/upload", content=b"x" * 100)

    assert small_route.status_code == 413
    assert upload_route.status_code == 200
