"""FastAPI application factory and health routes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from multimodal_rag.adapters.http.problems import (
    NOT_READY_CODE,
    install_problem_handlers,
    problem_response,
)

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


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

    @router.get("/health/live")
    async def liveness() -> dict[str, str]:
        """Report that the process is running."""
        return {"status": "alive"}

    @router.get("/health/ready", response_model=None)
    async def readiness(request: Request) -> dict[str, object] | JSONResponse:
        """Report whether every dependency of the API is reachable."""
        failing = []
        for name, check in readiness_checks.items():
            try:
                async with asyncio.timeout(timeout_seconds):
                    await check()
            except Exception:  # a probe can fail in any way, only its name matters
                logger.warning("readiness check %s failed", name, exc_info=True)
                failing.append(name)
        if failing:
            return problem_response(
                request,
                status=503,
                code=NOT_READY_CODE,
                detail=f"Unavailable: {', '.join(sorted(failing))}",
            )
        return {"status": "ready", "checks": sorted(readiness_checks)}

    return router


def create_app(
    *,
    readiness_checks: Mapping[str, ReadinessCheck],
    readiness_timeout_seconds: float = 2.0,
    routers: tuple[APIRouter, ...] = (),
    lifespan: Lifespan | None = None,
    version: str = "0.1.0",
) -> FastAPI:
    """Build the REST application.

    Args:
        readiness_checks: Named probes of the dependencies the API needs, such as the
            database and blob storage.
        readiness_timeout_seconds: Deadline of each readiness probe.
        routers: Feature routers to mount.
        lifespan: Startup and shutdown hook, such as disposing the database engine.
        version: Version reported in the OpenAPI document.

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
    return app
