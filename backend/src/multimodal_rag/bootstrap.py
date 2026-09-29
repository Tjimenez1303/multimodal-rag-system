"""Composition root: the only module that wires the domain core to its adapters.

It builds the API application and runs the worker. Starting processes from the command
line is the job of ``multimodal_rag.__main__``. User stories register their adapters and
routes here as they are implemented.
"""

import asyncio
import logging
import os
import signal
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp

from multimodal_rag import __version__
from multimodal_rag.adapters.clock import SystemClock
from multimodal_rag.adapters.docling.pdfium import PdfiumInspector
from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.body_limit import (
    MULTIPART_OVERHEAD_BYTES,
    BodyLimits,
)
from multimodal_rag.adapters.http.dependencies import IngestionState
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_ingestion import UPLOAD_PATH, ingestion_router
from multimodal_rag.adapters.postgres.documents import PostgresDocumentRepository
from multimodal_rag.adapters.postgres.elements import PostgresElementRepository
from multimodal_rag.adapters.postgres.engine import check_database, create_engine
from multimodal_rag.adapters.postgres.job_notifications import (
    PostgresJobNotifications,
)
from multimodal_rag.adapters.postgres.job_queue import PostgresJobQueue
from multimodal_rag.adapters.storage.filesystem import FilesystemBlobStorage
from multimodal_rag.adapters.worker.liveness import LivenessFile
from multimodal_rag.adapters.worker.loop import WorkerLoop
from multimodal_rag.ingestion.use_cases.intake import (
    GetJob,
    SubmitDocument,
    UploadLimits,
)
from multimodal_rag.ingestion.use_cases.processing import ProcessJob
from multimodal_rag.shared.config import ApiSettings, WorkerSettings
from multimodal_rag.shared.logging import configure_logging
from multimodal_rag.shared.resilience import RetryPolicy

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
    state = _ingestion_state(settings, engine, storage)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[IngestionState]:
        logger.info("api ready, version %s", __version__)
        yield state
        await engine.dispose()

    app = create_app(
        readiness_checks={
            "database": partial(check_database, engine),
            "blob_storage": storage.check_writable,
        },
        readiness_timeout_seconds=settings.readiness_timeout_seconds,
        routers=(ingestion_router,),
        lifespan=lifespan,
        version=__version__,
        body_limits=BodyLimits(
            by_path={UPLOAD_PATH: settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES}
        ),
    )
    # Outermost, so responses and logs of unhandled errors, which Starlette's
    # ServerErrorMiddleware produces outside user middleware, still carry the id.
    return RequestContextMiddleware(app)


def _ingestion_state(
    settings: ApiSettings, engine: AsyncEngine, storage: FilesystemBlobStorage
) -> IngestionState:
    clock = SystemClock()
    jobs = PostgresJobQueue(engine)
    return IngestionState(
        submit_document=SubmitDocument(
            documents=PostgresDocumentRepository(engine),
            jobs=jobs,
            blobs=storage,
            inspector=PdfiumInspector(),
            clock=clock,
            limits=UploadLimits(
                max_bytes=settings.max_upload_bytes,
                max_pages=settings.max_upload_pages,
            ),
            max_attempts=settings.max_attempts,
        ),
        get_job=GetJob(jobs=jobs),
    )


async def run_worker(*, stop: asyncio.Event | None = None) -> None:
    """Run the ingestion worker until it receives SIGTERM or SIGINT.

    Args:
        stop: Event that ends the worker when set. Signal handlers set it in
            production, and tests set it directly.

    Raises:
        ConfigurationError: If a required setting is missing or invalid.
    """
    settings = WorkerSettings.load()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    stop = stop or _stop_on_signals()
    liveness = LivenessFile(settings.liveness_file)
    logger.info(
        "worker starting, version %s, vision model %s, embedding model %s",
        __version__,
        settings.vlm_model,
        settings.embedder_model,
    )
    engine = create_engine(settings)
    notifications = PostgresJobNotifications(
        settings.database_url,
        timeout_seconds=settings.db_connect_timeout_seconds,
    )
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(
                liveness.keep_alive(
                    stop=stop, interval_seconds=settings.liveness_interval_seconds
                )
            )
            group.create_task(_serve_jobs(settings, engine, notifications, stop))
    finally:
        await notifications.close()
        await engine.dispose()
    logger.info("worker stopped")


async def _serve_jobs(
    settings: WorkerSettings,
    engine: AsyncEngine,
    notifications: PostgresJobNotifications,
    stop: asyncio.Event,
) -> None:
    if stop.is_set():
        return
    # Imported here so the API process never loads torch and the extraction models.
    from multimodal_rag.adapters.docling.extractor import DoclingExtractor

    extractor = DoclingExtractor(
        artifacts_path=settings.docling_artifacts_path,
        threads=settings.extraction_threads,
        batch_timeout_seconds=settings.extraction_batch_timeout_seconds,
    )
    await asyncio.to_thread(extractor.warm_up)
    storage = FilesystemBlobStorage(settings.blob_root)
    jobs = PostgresJobQueue(engine)
    process = ProcessJob(
        documents=PostgresDocumentRepository(engine),
        jobs=jobs,
        elements=PostgresElementRepository(engine),
        blobs=storage,
        extractor=extractor,
        page_batch=settings.extraction_page_batch,
    )
    logger.info("worker ready")
    await WorkerLoop(
        jobs=jobs,
        process=process,
        wakeups=notifications,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        lease_seconds=settings.lease_seconds,
        heartbeat_seconds=settings.heartbeat_seconds,
        poll_seconds=settings.poll_seconds,
        claim_retry=RetryPolicy.for_claims(settings),
        max_jobs=settings.worker_max_jobs,
    ).run(stop=stop)
    # The loop also returns after its job budget, and the liveness task stops too.
    stop.set()


def worker_is_alive() -> bool:
    """Report whether the worker touched its liveness file recently enough.

    Used by the container healthcheck, so the file and the age limit come from the
    same settings the worker uses.

    Returns:
        ``True`` when the file exists and is younger than ``LIVENESS_MAX_AGE_SECONDS``.

    Raises:
        ConfigurationError: If a required setting is missing or invalid.
    """
    settings = WorkerSettings.load()
    age = LivenessFile(settings.liveness_file).age_seconds()
    return age is not None and age <= settings.liveness_max_age_seconds


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    return stop
