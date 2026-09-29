"""Composition root: the only module that wires the domain core to its adapters.

It builds the API application and runs the worker. Starting processes from the command
line is the job of ``multimodal_rag.__main__``. User stories register their adapters and
routes here as they are implemented.
"""

import asyncio
import logging
import math
import os
import signal
import socket
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial

import httpx
from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp

from multimodal_rag import __version__
from multimodal_rag.adapters.clock import SystemClock
from multimodal_rag.adapters.concurrency.anyio_slots import AnyioAnswerSlots
from multimodal_rag.adapters.docling.pdfium import PdfiumInspector
from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.body_limit import (
    MULTIPART_OVERHEAD_BYTES,
    BodyLimits,
)
from multimodal_rag.adapters.http.dependencies import AnsweringState, IngestionState
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.adapters.http.routes_ingestion import UPLOAD_PATH, ingestion_router
from multimodal_rag.adapters.http.routes_questions import questions_router
from multimodal_rag.adapters.language.py3langid_identifier import Py3LangidIdentifier
from multimodal_rag.adapters.openai_compatible.answerer import (
    OpenAICompatibleAnswerGenerator,
)
from multimodal_rag.adapters.openai_compatible.describer import (
    OpenAICompatibleFigureDescriber,
)
from multimodal_rag.adapters.openai_compatible.embedder import (
    OpenAICompatibleEmbedder,
)
from multimodal_rag.adapters.postgres.documents import PostgresDocumentRepository
from multimodal_rag.adapters.postgres.elements import PostgresElementRepository
from multimodal_rag.adapters.postgres.engine import check_database, create_engine
from multimodal_rag.adapters.postgres.job_notifications import (
    PostgresJobNotifications,
)
from multimodal_rag.adapters.postgres.job_queue import PostgresJobQueue
from multimodal_rag.adapters.qdrant.index import QdrantVectorIndex
from multimodal_rag.adapters.storage.filesystem import FilesystemBlobStorage
from multimodal_rag.adapters.tokenizer.huggingface import HuggingFaceTokenCounter
from multimodal_rag.adapters.worker.liveness import LivenessFile
from multimodal_rag.adapters.worker.loop import WorkerLoop
from multimodal_rag.answering.use_cases.ask import AnsweringOptions, AnswerQuestion
from multimodal_rag.ingestion.figures import FigurePolicy
from multimodal_rag.ingestion.ports import DocumentExtractor
from multimodal_rag.ingestion.use_cases.intake import (
    GetJob,
    SubmitDocument,
    UploadLimits,
)
from multimodal_rag.ingestion.use_cases.library import (
    GetDocument,
    GetElementImage,
    ListDocumentElements,
    ListDocuments,
)
from multimodal_rag.ingestion.use_cases.processing import (
    EnrichmentOptions,
    ProcessJob,
)
from multimodal_rag.shared.config import ApiSettings, WorkerSettings
from multimodal_rag.shared.logging import configure_logging
from multimodal_rag.shared.resilience import RetryPolicy

logger = logging.getLogger(__name__)


class ApiState(IngestionState, AnsweringState):
    """Lifespan state of the API: every use case its routes serve."""


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
    ingestion = _ingestion_state(settings, engine, storage)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[ApiState]:
        async with AsyncExitStack() as resources:
            resources.push_async_callback(engine.dispose)
            answering = await _answering_state(settings, engine, storage, resources)
            logger.info("api ready, version %s", __version__)
            yield ApiState(**ingestion, **answering)

    app = create_app(
        readiness_checks={
            "database": partial(check_database, engine),
            "blob_storage": storage.check_writable,
        },
        readiness_timeout_seconds=settings.readiness_timeout_seconds,
        routers=(ingestion_router, documents_router, questions_router),
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
    documents = PostgresDocumentRepository(engine)
    elements = PostgresElementRepository(engine)
    return IngestionState(
        submit_document=SubmitDocument(
            documents=documents,
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
        list_document_elements=ListDocumentElements(
            documents=documents, jobs=jobs, elements=elements
        ),
        get_element_image=GetElementImage(elements=elements, blobs=storage),
        list_documents=ListDocuments(documents=documents, jobs=jobs),
        get_document=GetDocument(documents=documents, jobs=jobs),
    )


async def _answering_state(
    settings: ApiSettings,
    engine: AsyncEngine,
    storage: FilesystemBlobStorage,
    resources: AsyncExitStack,
) -> AnsweringState:
    # No client connects here, so the API starts while Qdrant or the models are down.
    retry = RetryPolicy.for_providers(settings)
    qdrant = AsyncQdrantClient(
        url=str(settings.qdrant_url),
        timeout=math.ceil(settings.qdrant_timeout_seconds),
        # The version check would call Qdrant from a thread at startup.
        check_compatibility=False,
    )
    resources.push_async_callback(qdrant.close)
    embedder_client = await resources.enter_async_context(
        httpx.AsyncClient(
            base_url=str(settings.embedder_url),
            timeout=settings.embedder_timeout_seconds,
        )
    )
    answer_client = await resources.enter_async_context(
        httpx.AsyncClient(
            base_url=str(settings.answer_model_url),
            timeout=settings.answer_model_timeout_seconds,
        )
    )
    return AnsweringState(
        answer_question=AnswerQuestion(
            embedder=OpenAICompatibleEmbedder(
                embedder_client,
                model=settings.embedder_model,
                dimensions=settings.embedder_dimensions,
                batch_size=settings.embedder_batch_size,
                query_instruction=settings.embedder_query_instruction,
                retry=retry,
            ),
            index=QdrantVectorIndex(
                qdrant,
                collection=settings.qdrant_collection,
                dimensions=settings.embedder_dimensions,
                retry=retry,
            ),
            documents=PostgresDocumentRepository(engine),
            elements=PostgresElementRepository(engine),
            generator=OpenAICompatibleAnswerGenerator(
                answer_client,
                model=settings.answer_model,
                max_tokens=settings.answer_max_tokens,
                temperature=settings.answer_temperature,
                retry=retry,
            ),
            languages=Py3LangidIdentifier(),
            blobs=storage,
            slots=AnyioAnswerSlots(
                capacity=settings.answer_concurrency,
                queue_limit=settings.answer_queue_limit,
            ),
            options=AnsweringOptions(
                top_k=settings.retrieval_top_k,
                max_question_chars=settings.max_question_chars,
                max_filter_documents=settings.max_filter_documents,
                low_confidence_threshold=settings.low_confidence_threshold,
                min_similarity=settings.min_similarity,
                attribution_min_score=settings.attribution_min_score,
                deadline_seconds=settings.answer_deadline_seconds,
            ),
        )
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
    jobs = PostgresJobQueue(engine)
    async with AsyncExitStack() as clients:
        process = await _process_job(settings, engine, jobs, extractor, clients)
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


async def _process_job(
    settings: WorkerSettings,
    engine: AsyncEngine,
    jobs: PostgresJobQueue,
    extractor: DocumentExtractor,
    clients: AsyncExitStack,
) -> ProcessJob:
    retry = RetryPolicy.for_providers(settings)
    qdrant = AsyncQdrantClient(
        url=str(settings.qdrant_url),
        timeout=math.ceil(settings.qdrant_timeout_seconds),
    )
    clients.push_async_callback(qdrant.close)
    index = QdrantVectorIndex(
        qdrant,
        collection=settings.qdrant_collection,
        dimensions=settings.embedder_dimensions,
        retry=retry,
    )
    await index.ensure_collection()
    embedder_client = await clients.enter_async_context(
        httpx.AsyncClient(
            base_url=str(settings.embedder_url),
            timeout=settings.embedder_timeout_seconds,
        )
    )
    describer = None
    if settings.figure_description_enabled:
        vlm_client = await clients.enter_async_context(
            httpx.AsyncClient(
                base_url=str(settings.vlm_url), timeout=settings.vlm_timeout_seconds
            )
        )
        describer = OpenAICompatibleFigureDescriber(
            vlm_client, model=settings.vlm_model, retry=retry
        )
    return ProcessJob(
        documents=PostgresDocumentRepository(engine),
        jobs=jobs,
        elements=PostgresElementRepository(engine),
        blobs=FilesystemBlobStorage(settings.blob_root),
        extractor=extractor,
        describer=describer,
        embedder=OpenAICompatibleEmbedder(
            embedder_client,
            model=settings.embedder_model,
            dimensions=settings.embedder_dimensions,
            batch_size=settings.embedder_batch_size,
            query_instruction=settings.embedder_query_instruction,
            retry=retry,
        ),
        token_counter=HuggingFaceTokenCounter.from_file(
            settings.embedder_tokenizer_path
        ),
        index=index,
        page_batch=settings.extraction_page_batch,
        enrichment=EnrichmentOptions(
            figure_policy=FigurePolicy(
                decorative_min_pages=settings.decorative_min_pages,
                decorative_min_page_share=settings.decorative_min_page_share,
            ),
            figure_concurrency=settings.figure_concurrency,
            near_text_max_points=settings.near_text_max_points,
            max_unit_tokens=settings.max_unit_tokens,
            embedder_max_input_tokens=settings.embedder_max_input_tokens,
        ),
    )


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
