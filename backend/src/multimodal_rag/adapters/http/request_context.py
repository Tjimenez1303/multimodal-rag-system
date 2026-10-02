"""Middleware that gives every request a correlation id and one summary log line."""

import logging
import re
import time
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from multimodal_rag.shared.logging import bind_correlation, clear_correlation

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"

# Incoming ids are reused only when short and made of safe characters
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# Probed every few seconds by the orchestrator, so logged below INFO.
_QUIET_ROUTES = frozenset({"/health/live", "/health/ready"})


class RequestContextMiddleware:
    """Binds a correlation id to each request and logs one line when it completes.

    The id comes from ``X-Request-ID`` when it is short and made of safe characters,
    so a caller cannot inject content into logs or headers, and is generated
    otherwise. It is echoed in the response, exposed to handlers as
    ``request.state.request_id`` and bound to every log record of the request. When
    the request completes, one structured line records the method, the route
    template, the status and the duration. The query string and the client address
    are never logged. Being pure ASGI, the middleware does not buffer bodies such as
    large uploads.

    Args:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call."""
        # Only HTTP requests are tracked; other ASGI calls pass through
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Reuse the caller's id or create one, and store it for the handlers
        request_id = self._incoming_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        response_started = False
        started = time.perf_counter()

        # Copy the id into the response headers and remember the status sent
        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        # Tag every log line of this request with its id
        clear_correlation()
        bind_correlation(request_id=request_id)
        try:
            await self._app(scope, receive, send_with_id)
        except Exception:
            # Starlette re-raises an error after its 500 response so the server can
            # log it. The problem handler already logged it with the request id, so
            # it ends here once answered, and the server does not log it again.
            if status != 500 or not response_started:
                raise
        finally:
            # Always write the summary line and clear the log context
            self._log_completion(scope, status=status, started=started)
            clear_correlation()

    @staticmethod
    def _log_completion(scope: Scope, *, status: int, started: float) -> None:
        # Starlette stores the matched route in the scope, unmatched paths have none.
        route = getattr(scope.get("route"), "path", None)

        # OpenTelemetry-style fields of the summary line
        fields: dict[str, object] = {
            "http.request.method": scope["method"],
            "http.response.status_code": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if route is not None:
            fields["http.route"] = route

        # Health probes are logged at DEBUG to keep the logs readable
        level = logging.DEBUG if route in _QUIET_ROUTES else logging.INFO
        logger.log(level, "request completed", extra=fields)

    @staticmethod
    def _incoming_id(scope: Scope) -> str | None:
        # Find the X-Request-ID header, if the client sent a usable one
        for name, value in scope.get("headers", []):
            if name.decode("latin-1").lower() == REQUEST_ID_HEADER:
                candidate = value.decode("latin-1")
                return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else None
        return None


def request_id_of(request: Request) -> str:
    """Return the correlation id of a request.

    ``RequestContextMiddleware`` assigns it. An app served without that middleware,
    as in some tests, gets a new id that is kept for the rest of the request.

    Args:
        request: Request being handled.

    Returns:
        The id, 32 hex characters when generated.
    """
    # Requests that skipped the middleware still get an id
    request_id: str | None = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
    return request_id
