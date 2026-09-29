"""FastAPI application factory and health routes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.types import Lifespan

from multimodal_rag.adapters.http.body_limit import BodyLimits, BodySizeLimitMiddleware
from multimodal_rag.adapters.http.problems import (
    NOT_READY_CODE,
    PROBLEM_MEDIA_TYPE,
    Problem,
    install_problem_handlers,
    problem_response,
    problem_responses,
)

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]


def health_router(
    *, readiness_checks: Mapping[str, ReadinessCheck], timeout_seconds: float
) -> APIRouter:
    """Build the liveness and readiness routes.

    Args:
        readiness_checks: Named probes of the dependencies the API needs. Each raises
            when its dependency is unusable.
        timeout_seconds: Deadline of each probe, so a hanging dependency cannot make
            readiness slower than the orchestrator's own probe timeout.

    Returns:
        A router serving ``/health/live`` and ``/health/ready``.
    """
    router = APIRouter(tags=["health"])

    @router.get(
        "/health/live",
        operation_id="liveness",
        description="The process is running.",
    )
    async def liveness() -> dict[str, str]:
        """Report that the process is running.

        Returns:
            A fixed body, since answering at all proves liveness.
        """
        return {"status": "alive"}

    @router.get(
        "/health/ready",
        operation_id="readiness",
        description="Dependencies (database, blob storage) are reachable.",
        response_model=None,
        responses=problem_responses(503),
    )
    async def readiness(request: Request) -> dict[str, object] | JSONResponse:
        """Report whether every dependency of the API is reachable.

        Args:
            request: Request being answered.

        Returns:
            The checked dependencies, or 503 problem details naming the failing ones.
        """
        failing = await _failing_checks(readiness_checks, timeout_seconds)
        if failing:
            return problem_response(
                request,
                status=503,
                code=NOT_READY_CODE,
                detail=f"Unavailable: {', '.join(sorted(failing))}",
            )
        return {"status": "ready", "checks": sorted(readiness_checks)}

    return router


async def _failing_checks(
    checks: Mapping[str, ReadinessCheck], timeout_seconds: float
) -> list[str]:
    # Concurrent probes, so the whole check takes at most one probe timeout.
    async def probe(name: str, check: ReadinessCheck) -> str | None:
        try:
            async with asyncio.timeout(timeout_seconds):
                await check()
        except Exception:  # a probe can fail in any way, only its name matters
            logger.warning("readiness check %s failed", name, exc_info=True)
            return name
        return None

    results = await asyncio.gather(*(probe(n, c) for n, c in checks.items()))
    return [name for name in results if name is not None]


def create_app(
    *,
    readiness_checks: Mapping[str, ReadinessCheck],
    readiness_timeout_seconds: float = 2.0,
    routers: tuple[APIRouter, ...] = (),
    lifespan: Lifespan[FastAPI] | None = None,
    version: str = "0.1.0",
    body_limits: BodyLimits | None = None,
) -> FastAPI:
    """Build the REST application.

    Args:
        readiness_checks: Named probes of the dependencies the API needs, such as the
            database and blob storage.
        readiness_timeout_seconds: Deadline of each readiness probe.
        routers: Feature routers to mount.
        lifespan: Startup and shutdown hook, such as disposing the database engine.
            The state it yields is copied into every request.
        version: Version reported in the OpenAPI document.
        body_limits: Largest request body per route. Defaults to the small default
            limit on every route.

    Returns:
        The FastAPI application. The composition root wraps it with the request id
        middleware.
    """
    app = FastAPI(
        title="Multimodal RAG ingestion API", version=version, lifespan=lifespan
    )
    install_problem_handlers(app)
    app.include_router(
        health_router(
            readiness_checks=readiness_checks,
            timeout_seconds=readiness_timeout_seconds,
        )
    )
    for router in routers:
        app.include_router(router)
    app.add_middleware(BodySizeLimitMiddleware, limits=body_limits or BodyLimits())
    app.openapi = _problem_aware_openapi(app)  # type: ignore[method-assign]
    return app


_PROBLEM_REF = {"$ref": f"#/components/schemas/{Problem.__name__}"}
_VALIDATION_REF = {"$ref": "#/components/schemas/HTTPValidationError"}


def _problem_aware_openapi(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """Build the OpenAPI document with the responses the API really sends.

    FastAPI documents every extra response as ``application/json`` and adds a 422
    validation response to routes with parameters. The document is generated once and
    then corrected: problem bodies move to ``application/problem+json``, and the 422 is
    dropped because validation errors are answered with 400 problem details.
    """

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, routes=app.routes
            )
            for operation in _operations(schema):
                _correct_responses(operation["responses"])
            components = schema.get("components", {}).get("schemas", {})
            for unused in ("HTTPValidationError", "ValidationError"):
                components.pop(unused, None)
            app.openapi_schema = schema
        return app.openapi_schema

    return openapi


def _operations(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        operation
        for path_item in schema.get("paths", {}).values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "responses" in operation
    ]


def _correct_responses(responses: dict[str, Any]) -> None:
    for status in list(responses):
        content = responses[status].get("content", {})
        body = content.get("application/json", {}).get("schema")
        if body == _VALIDATION_REF:
            del responses[status]
        elif body == _PROBLEM_REF:
            content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
