"""RFC 9457 problem details, the single place that maps errors to HTTP statuses.

Every problem uses the ``about:blank`` type, so its ``title`` is the standard phrase of
its status (RFC 9457 section 4.2.1). The specific cause travels in the ``code``
extension member and, for client errors, in ``detail``.
"""

import logging
import re
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
PROBLEM_TYPE = "about:blank"
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
) -> JSONResponse:
    """Build an RFC 9457 response.

    Args:
        request: Request being answered.
        status: HTTP status code.
        code: Stable machine-readable code.
        detail: Explanation specific to this occurrence, if safe to share.

    Returns:
        A JSON response with the ``application/problem+json`` media type.
    """
    body: dict[str, Any] = {
        "type": PROBLEM_TYPE,
        "title": HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", ""),
    }
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


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
    return problem_response(
        request,
        status=error.status_code,
        code=http_problem_code(error.status_code),
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
