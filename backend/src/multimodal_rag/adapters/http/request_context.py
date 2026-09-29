"""Middleware that gives every request a correlation id and one summary log line."""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from multimodal_rag.shared.logging import bind_correlation, clear_correlation

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"
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
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = self._incoming_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        clear_correlation()
        bind_correlation(request_id=request_id)
        try:
            await self._app(scope, receive, send_with_id)
        finally:
            self._log_completion(scope, status=status, started=started)
            clear_correlation()

    @staticmethod
    def _log_completion(scope: Scope, *, status: int, started: float) -> None:
        # Starlette stores the matched route in the scope, unmatched paths have none.
        route = getattr(scope.get("route"), "path", None)
        fields: dict[str, object] = {
            "http.request.method": scope["method"],
            "http.response.status_code": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if route is not None:
            fields["http.route"] = route
        level = logging.DEBUG if route in _QUIET_ROUTES else logging.INFO
        logger.log(level, "request completed", extra=fields)

    @staticmethod
    def _incoming_id(scope: Scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name.decode("latin-1").lower() == REQUEST_ID_HEADER:
                candidate = value.decode("latin-1")
                return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else None
        return None
