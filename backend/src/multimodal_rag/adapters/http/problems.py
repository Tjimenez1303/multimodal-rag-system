"""RFC 9457 problem details, the single place that maps errors to HTTP statuses.

Every problem uses the ``about:blank`` type, so its ``title`` is the standard phrase of
its status (RFC 9457 section 4.2.1). The specific cause travels in the ``code``
extension member and, for client errors, in ``detail``.
"""

import logging
import re
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from multimodal_rag.adapters.http.request_context import request_id_of
from multimodal_rag.ingestion.errors import (
    FileTooLargeError,
    PageLimitExceededError,
    UnsupportedMediaTypeError,
)
from multimodal_rag.shared.errors import (
    ConcurrencyError,
    ConfigurationError,
    DataInconsistencyError,
    ExtractionError,
    MultimodalRagError,
    NotFoundError,
    ProviderError,
    StorageError,
    ValidationError,
)

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
# Same pattern as Problem.code in the OpenAPI contract.
PROBLEM_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NOT_READY_CODE = "not_ready"

# Most specific classes first: the first match along the error's MRO wins.
_STATUS_BY_ERROR: dict[type[MultimodalRagError], int] = {
    UnsupportedMediaTypeError: 415,
    FileTooLargeError: 413,
    PageLimitExceededError: 422,
    ValidationError: 400,
    NotFoundError: 404,
    ConcurrencyError: 409,
    ExtractionError: 422,
    ProviderError: 503,
    StorageError: 503,
    ConfigurationError: 500,
    DataInconsistencyError: 500,
    MultimodalRagError: 500,
}


class ProblemHTTPException(StarletteHTTPException):
    """HTTP error raised outside a route that carries its own problem code.

    Middleware raises it while the request body is being read, where FastAPI only
    propagates HTTP exceptions.

    Args:
        status_code: HTTP status code.
        code: Stable machine-readable code.
        detail: Explanation safe to share with the client.
    """

    def __init__(self, *, status_code: int, code: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class Problem(BaseModel):
    """RFC 9457 problem details, the body of every error response.

    Attributes:
        type: Always ``about:blank``, so ``title`` is the phrase of the status.
        title: Standard phrase of the HTTP status.
        status: HTTP status code.
        detail: Explanation of this occurrence, sent for client errors only.
        instance: Path of the request.
        code: Stable machine-readable code in lowercase snake case.
        request_id: Correlation id of the request.
    """

    type: Literal["about:blank"] = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str
    code: str = Field(pattern=PROBLEM_CODE_PATTERN.pattern)
    request_id: str


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document problem responses for a route's ``responses`` argument.

    Args:
        statuses: HTTP statuses the route can answer with problem details.

    Returns:
        The OpenAPI response entries, whose media type ``create_app`` rewrites to
        ``application/problem+json``.
    """
    return {status: {"model": Problem} for status in statuses}


def status_for(error: MultimodalRagError) -> int:
    """Return the HTTP status of an error, walking its class hierarchy.

    Args:
        error: A domain or infrastructure error.

    Returns:
        The status mapped to the most specific class of the error.
    """
    for cls in type(error).__mro__:
        if cls in _STATUS_BY_ERROR:
            return _STATUS_BY_ERROR[cls]
    return 500  # pragma: no cover - MultimodalRagError is always in the MRO


def http_problem_code(status: int) -> str:
    """Return the problem code of a plain HTTP error, such as ``method_not_allowed``.

    Args:
        status: HTTP status code.

    Returns:
        The status phrase in lowercase snake case, with punctuation removed.
    """
    return re.sub(r"[^a-z0-9]+", "_", HTTPStatus(status).phrase.lower()).strip("_")


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build an RFC 9457 response.

    Args:
        request: Request being answered.
        status: HTTP status code.
        code: Stable machine-readable code.
        detail: Explanation specific to this occurrence, if safe to share.
        headers: Headers the status requires, such as ``Allow`` on a 405.

    Returns:
        A JSON response with the ``application/problem+json`` media type.
    """
    problem = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail or None,
        instance=request.url.path,
        code=code,
        request_id=request_id_of(request),
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def _handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, MultimodalRagError)
    status = status_for(error)
    if status >= 500:
        # Internal details stay in the logs, and clients only get the stable code.
        logger.error("request failed with %s", error.code, exc_info=error)
        return problem_response(request, status=status, code=error.code)
    return problem_response(request, status=status, code=error.code, detail=str(error))


async def _handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    fields = ", ".join(
        ".".join(str(part) for part in issue["loc"]) for issue in error.errors()
    )
    return problem_response(
        request,
        status=400,
        code=ValidationError.code,
        detail=f"Invalid or missing fields: {fields}",
    )


async def _handle_http_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    if isinstance(error, ProblemHTTPException):
        return problem_response(
            request, status=error.status_code, code=error.code, detail=error.detail
        )
    return problem_response(
        request,
        status=error.status_code,
        code=http_problem_code(error.status_code),
        headers=error.headers,
    )


async def _handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.error("unexpected error while handling a request", exc_info=error)
    return problem_response(request, status=500, code=MultimodalRagError.code)


def install_problem_handlers(app: FastAPI) -> None:
    """Register the handlers that turn every error into problem details.

    Args:
        app: Application to configure.
    """
    app.add_exception_handler(MultimodalRagError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
