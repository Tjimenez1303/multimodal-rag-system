"""Request body size limits enforced before the body is parsed.

FastAPI parses a multipart body completely before any dependency or route runs, so a
route cannot refuse an oversized upload early. This pure ASGI middleware answers 413
from the declared ``Content-Length`` without reading the body, and counts the bytes of
bodies sent without that header, as Starlette's ``RequestBodyLimitMiddleware`` does,
but with RFC 9457 problem details. Upload routes get their own limit, and every other
route gets a small default.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from multimodal_rag.adapters.http.problems import (
    ProblemHTTPException,
    problem_response,
    status_for,
)
from multimodal_rag.ingestion.errors import FileTooLargeError

# Room for the multipart boundaries and part headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
# Same bound Starlette puts on each non-file form field.
DEFAULT_BODY_BYTES = 1024 * 1024
# The status comes from the single error-to-status mapping of the API.
_STATUS = status_for(FileTooLargeError())


@dataclass(frozen=True, slots=True)
class BodyLimits:
    """Largest request body accepted per route.

    Attributes:
        default_bytes: Limit of routes not listed in ``by_path``.
        by_path: Limit of specific paths, such as an upload route.
    """

    default_bytes: int = DEFAULT_BODY_BYTES
    by_path: Mapping[str, int] = field(default_factory=dict)

    def for_path(self, path: str) -> int:
        """Return the limit that applies to a request path.

        Args:
            path: Path of the request, without the application's root path.

        Returns:
            The largest accepted body in bytes.
        """
        return self.by_path.get(path, self.default_bytes)


class BodySizeLimitMiddleware:
    """Refuses request bodies larger than their route's limit with 413 problems.

    Args:
        app: The wrapped ASGI application.
        limits: Body limits per route.
    """

    def __init__(self, app: ASGIApp, *, limits: BodyLimits) -> None:
        self._app = app
        self._limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call.

        Args:
            scope: Connection scope.
            receive: Channel that yields request messages.
            send: Channel that takes response messages.

        Raises:
            ProblemHTTPException: If a body without ``Content-Length`` grows past the
                limit while it is read.
        """
        # Only HTTP requests carry a body; other ASGI calls pass through
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Find the limit of this route
        path = scope["path"].removeprefix(scope.get("root_path", ""))
        limit = self._limits.for_path(path)
        detail = f"The request body exceeds the limit of {limit} bytes"

        # Refuse at once when the declared length is already too large
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            response = problem_response(
                Request(scope),
                status=_STATUS,
                code=FileTooLargeError.code,
                detail=detail,
            )
            await response(scope, receive, send)
            return

        # Otherwise count the bytes as they arrive and stop past the limit
        received = 0

        async def receive_with_limit() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise ProblemHTTPException(
                        status_code=_STATUS, code=FileTooLargeError.code, detail=detail
                    )
            return message

        # Hand the request to the app with the counting receive
        await self._app(scope, receive_with_limit, send)


def _content_length(scope: Scope) -> int | None:
    # Only ASCII digits form a valid Content-Length.
    value = Headers(scope=scope).get("content-length")
    if value is None or not (value.isascii() and value.isdigit()):
        return None
    return int(value)
