"""Application settings loaded from environment variables.

The API, the worker and the migration command read different settings, so each process
requires only what it uses. Required settings have no default and stop the process at
startup with a message that names every missing or invalid variable.
"""

from pathlib import Path
from typing import Literal, Self

import pydantic
from pydantic import Field, HttpUrl, PositiveFloat, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

from multimodal_rag.shared.errors import ConfigurationError

_MEGABYTE = 1024 * 1024


class DatabaseSettings(BaseSettings):
    """Settings of every process that talks to the database, migrations included.

    Attributes:
        database_url: SQLAlchemy URL of the PostgreSQL database, using asyncpg.
        log_format: ``json`` for production logs, ``console`` for local reading.
        log_level: Minimum level of emitted log records.
        db_connect_timeout_seconds: Maximum time to open a database connection.
        db_statement_timeout_ms: Maximum run time of one SQL statement.
        db_pool_size: Connections kept open per process.
        db_pool_timeout_seconds: Maximum wait for a free pooled connection.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    database_url: str = Field(pattern=r"^postgresql\+asyncpg://")
    log_format: Literal["json", "console"] = "json"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    db_connect_timeout_seconds: PositiveFloat = 5.0
    db_statement_timeout_ms: PositiveInt = 15_000
    db_pool_size: PositiveInt = 10
    db_pool_timeout_seconds: PositiveFloat = 10.0

    @classmethod
    def load(cls) -> Self:
        """Load and validate settings from the environment.

        Returns:
            The validated settings.

        Raises:
            ConfigurationError: If a required variable is missing or a value is
                invalid. The message names every offending variable.
        """
        try:
            return cls()
        except pydantic.ValidationError as error:
            problems = ", ".join(
                f"{'_'.join(str(part) for part in issue['loc']).upper()} "
                f"({issue['msg']})"
                for issue in error.errors()
            )
            raise ConfigurationError(f"Invalid configuration: {problems}") from error


class CommonSettings(DatabaseSettings):
    """Settings shared by the API and the worker.

    Attributes:
        blob_root: Directory of the shared volume that stores PDFs and figure crops.
        max_attempts: Attempts allowed for one ingestion job before it fails. The API
            stores it on each job it creates, so both processes must agree on it.
    """

    blob_root: Path
    max_attempts: PositiveInt = 3


class ProviderSettings(CommonSettings):
    """Settings of the external services that the API and the worker both call.

    Attributes:
        qdrant_url: Base URL of the Qdrant server.
        qdrant_collection: Collection that stores retrieval units.
        qdrant_timeout_seconds: Timeout of each call to Qdrant.
        embedder_url: OpenAI-compatible base URL of the embedding model.
        embedder_model: Model reference of the embedding model.
        embedder_timeout_seconds: Timeout of one embedding request.
        embedder_dimensions: Length of the embedding vectors.
        embedder_batch_size: Passages sent per embedding request.
        embedder_query_instruction: Task sentence prepended to questions before
            they are embedded, as the embedding model expects for retrieval.
        provider_retry_attempts: Attempts for a transient provider failure.
        provider_retry_initial_wait_seconds: First backoff wait before jitter.
        provider_retry_max_wait_seconds: Longest backoff wait.
        provider_retry_jitter_seconds: Largest random amount added to each wait.
        provider_retry_timeout_seconds: Total time budget across all attempts.
    """

    qdrant_url: HttpUrl
    qdrant_collection: str = "retrieval_units"
    qdrant_timeout_seconds: PositiveFloat = 10.0
    embedder_url: HttpUrl
    embedder_model: str = Field(min_length=1)
    embedder_timeout_seconds: PositiveFloat = 60.0
    embedder_dimensions: PositiveInt = 1024
    embedder_batch_size: PositiveInt = 32
    embedder_query_instruction: str = Field(
        default=(
            "Given a question about a technical manual, "
            "retrieve the passages that answer it"
        ),
        min_length=1,
    )
    provider_retry_attempts: PositiveInt = 4
    provider_retry_initial_wait_seconds: PositiveFloat = 0.5
    provider_retry_max_wait_seconds: PositiveFloat = 10.0
    provider_retry_jitter_seconds: float = Field(default=1.0, ge=0)
    provider_retry_timeout_seconds: PositiveFloat = 300.0


class ApiSettings(ProviderSettings):
    """Settings of the REST API process.

    Attributes:
        max_upload_bytes: Largest accepted PDF, 200 MB by default.
        max_upload_pages: Largest accepted page count, 500 by default.
        api_host: Interface the server listens on inside its container.
        api_port: Port the server listens on inside its container.
        readiness_timeout_seconds: Deadline of each readiness probe.
        answer_model_url: OpenAI-compatible base URL of the answer model.
        answer_model: Model reference of the answer model.
        answer_model_timeout_seconds: Timeout of one answer generation request.
        answer_max_tokens: Longest answer the model may write, in tokens.
        answer_temperature: Sampling temperature of the answer model.
        retrieval_top_k: Retrieval units supplied to the answer model.
        min_similarity: Lowest dense similarity that lets a unit pass the relevance
            gate.
        low_confidence_threshold: Recognition confidence below which a source is
            flagged as low-confidence recognized text.
        max_question_chars: Longest question, after trimming.
        max_filter_documents: Most documents a question may be restricted to.
        answer_concurrency: Questions answered at the same time.
        answer_queue_limit: Questions allowed to wait for a free place.
        answer_deadline_seconds: Total time of a question, waiting included.
        attribution_min_score: Lowest match that attributes a statement of an answer
            written without source markers.
    """

    max_upload_bytes: PositiveInt = 200 * _MEGABYTE
    max_upload_pages: PositiveInt = 500
    # All interfaces inside the container, while compose publishes 127.0.0.1 only.
    api_host: str = "0.0.0.0"
    api_port: PositiveInt = 8000
    readiness_timeout_seconds: PositiveFloat = 2.0
    answer_model_url: HttpUrl
    answer_model: str = Field(min_length=1)
    answer_model_timeout_seconds: PositiveFloat = 60.0
    answer_max_tokens: PositiveInt = 800
    answer_temperature: float = Field(default=0.0, ge=0, le=2)
    retrieval_top_k: PositiveInt = 8
    min_similarity: float = Field(default=0.60, ge=0, le=1)
    low_confidence_threshold: float = Field(default=0.90, ge=0, le=1)
    max_question_chars: PositiveInt = 2000
    max_filter_documents: PositiveInt = 20
    answer_concurrency: PositiveInt = 2
    answer_queue_limit: int = Field(default=6, ge=0)
    answer_deadline_seconds: PositiveFloat = 90.0
    attribution_min_score: float = Field(default=0.5, ge=0, le=1)

    @pydantic.model_validator(mode="after")
    def _generation_fits_the_deadline(self) -> Self:
        if self.answer_model_timeout_seconds >= self.answer_deadline_seconds:
            raise ValueError(
                "ANSWER_MODEL_TIMEOUT_SECONDS must be shorter than "
                "ANSWER_DEADLINE_SECONDS"
            )
        return self


class WorkerSettings(ProviderSettings):
    """Settings of the ingestion worker process.

    Attributes:
        vlm_url: OpenAI-compatible base URL of the vision model.
        vlm_model: Model reference of the vision model.
        vlm_timeout_seconds: Timeout of one figure description request.
        embedder_tokenizer_path: ``tokenizer.json`` of the embedding model, baked
            into the image.
        embedder_max_input_tokens: Longest input the embedding model accepts, the
            physical batch it runs with.
        lease_seconds: Lease granted to a worker for one job.
        heartbeat_seconds: Interval between lease renewals.
        poll_seconds: Fallback polling interval when no notification arrives.
        claim_retry_max_wait_seconds: Longest wait between two failed claims.
        claim_retry_jitter_seconds: Largest random amount added to each wait
            between failed claims.
        worker_max_jobs: Jobs processed before the process exits to be restarted.
        extraction_page_batch: Pages converted per extraction batch.
        extraction_threads: CPU threads used by the extraction models.
        extraction_batch_timeout_seconds: Longest conversion of one page batch.
        docling_artifacts_path: Directory with pre-downloaded extraction models, or
            ``None`` to let the extractor download them on first use.
        liveness_file: File the worker touches to prove it is alive.
        liveness_interval_seconds: Interval between two touches of the liveness file.
        liveness_max_age_seconds: Age after which the healthcheck reports the worker
            as stuck.
        figure_description_enabled: Whether figures are described by the model.
        figure_concurrency: Figures described in parallel.
        max_unit_tokens: Token ceiling of a retrieval unit.
        decorative_min_pages: Pages an image must repeat on to count as decorative.
        decorative_min_page_share: Share of pages an image must repeat on to count
            as decorative.
        near_text_max_points: Largest distance, in PDF points, for nearby text.
    """

    vlm_url: HttpUrl
    vlm_model: str = Field(min_length=1)
    vlm_timeout_seconds: PositiveFloat = 120.0
    embedder_tokenizer_path: Path
    embedder_max_input_tokens: PositiveInt = 2048
    lease_seconds: PositiveInt = 90
    heartbeat_seconds: PositiveInt = 30
    poll_seconds: PositiveFloat = 2.0
    claim_retry_max_wait_seconds: PositiveFloat = 30.0
    claim_retry_jitter_seconds: float = Field(default=1.0, ge=0)
    worker_max_jobs: PositiveInt = 20
    extraction_page_batch: PositiveInt = 4
    extraction_threads: PositiveInt = 4
    extraction_batch_timeout_seconds: PositiveFloat = 120.0
    docling_artifacts_path: Path | None = None
    liveness_file: Path = Path("/tmp/multimodal-rag-worker.alive")
    liveness_interval_seconds: PositiveFloat = 10.0
    liveness_max_age_seconds: PositiveFloat = 60.0
    figure_description_enabled: bool = True
    figure_concurrency: PositiveInt = 2
    max_unit_tokens: PositiveInt = 480
    decorative_min_pages: PositiveInt = 3
    decorative_min_page_share: float = Field(default=0.2, gt=0, le=1)
    near_text_max_points: PositiveFloat = 72.0

    @pydantic.model_validator(mode="after")
    def _intervals_fit_their_limits(self) -> Self:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("HEARTBEAT_SECONDS must be shorter than LEASE_SECONDS")
        if self.embedder_max_input_tokens < self.max_unit_tokens:
            raise ValueError(
                "EMBEDDER_MAX_INPUT_TOKENS must hold a whole unit of MAX_UNIT_TOKENS"
            )
        if self.liveness_interval_seconds >= self.liveness_max_age_seconds:
            raise ValueError(
                "LIVENESS_INTERVAL_SECONDS must be shorter than "
                "LIVENESS_MAX_AGE_SECONDS"
            )
        return self
