"""Composition root: the only module that wires the domain core to its adapters.

It builds the API application and runs the worker. Starting processes from the command
line is the job of ``multimodal_rag.__main__``. User stories register their adapters and
routes here as they are implemented.
"""

import asyncio
import logging
import signal
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from starlette.types import ASGIApp

from multimodal_rag import __version__
from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.postgres.engine import check_database, create_engine
from multimodal_rag.adapters.storage.filesystem import FilesystemBlobStorage
from multimodal_rag.adapters.worker.liveness import LivenessFile
from multimodal_rag.shared.config import ApiSettings, WorkerSettings
from multimodal_rag.shared.logging import configure_logging

logger = logging.getLogger(__name__)


def create_api_app() -> ASGIApp:
    """Build the REST API from environment settings.

    Returns:
        The application, ready to be served by uvicorn.

    Raises:
        ConfigurationError: If a required setting is missing or invalid.
    """
    settings = ApiSettings.load()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    engine = create_engine(settings)
    storage = FilesystemBlobStorage(settings.blob_root)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        logger.info("api ready, version %s", __version__)
        yield
        await engine.dispose()

    app = create_app(
        readiness_checks={
            "database": partial(check_database, engine),
            "blob_storage": storage.check_writable,
        },
        readiness_timeout_seconds=settings.readiness_timeout_seconds,
        lifespan=lifespan,
        version=__version__,
    )
    # Outermost, so responses and logs of unhandled errors, which Starlette's
    # ServerErrorMiddleware produces outside user middleware, still carry the id.
    return RequestContextMiddleware(app)


async def run_worker(*, stop: asyncio.Event | None = None) -> None:
    """Run the ingestion worker until it receives SIGTERM or SIGINT.

    Args:
        stop: Event that ends the worker when set. Signal handlers set it in
            production; tests set it directly.

    Raises:
        ConfigurationError: If a required setting is missing or invalid.
    """
    settings = WorkerSettings.load()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    stop = stop or _stop_on_signals()
    liveness = LivenessFile(settings.liveness_file)
    logger.info(
        "worker ready, version %s, vision model %s, embedding model %s",
        __version__,
        settings.vlm_model,
        settings.embedder_model,
    )
    await liveness.keep_alive(
        stop=stop, interval_seconds=settings.liveness_interval_seconds
    )
    logger.info("worker stopped")


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    return stop
