"""Structured logging over the standard library.

Modules log with ``logging.getLogger(__name__)`` and lazy ``%s`` arguments. structlog
renders every record, from the application or from libraries, as one JSON object in
production or as readable lines locally. Correlation ids bound with ``bind_correlation``
travel through context variables, so they appear on every record emitted while a request
or a job is being handled.
"""

import logging
import sys
from typing import Literal, TextIO

import structlog

LogFormat = Literal["json", "console"]

_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
]

# Libraries that log every conversion step at INFO. Below DEBUG only their warnings
# and errors are kept, because the worker already logs each job transition.
STEP_BY_STEP_LOGGERS = ("docling",)

# Fields of the per-request log line, passed through the stdlib ``extra`` argument.
# Named after the OpenTelemetry HTTP semantic conventions.
REQUEST_LOG_FIELDS = (
    "http.request.method",
    "http.route",
    "http.response.status_code",
    "duration_ms",
)


def configure_logging(
    *, log_format: LogFormat, level: str = "INFO", stream: TextIO | None = None
) -> None:
    """Route every log record through structlog with a single root handler.

    Args:
        log_format: ``json`` renders one JSON object per record, ``console`` renders
            human-readable lines.
        level: Minimum level of emitted records, such as ``INFO``. Libraries in
            ``STEP_BY_STEP_LOGGERS`` emit only warnings unless it is ``DEBUG``.
        stream: Destination of the rendered records. Defaults to standard output.
    """
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # An allow list keeps other libraries' extras, such as uvicorn's, out.
        foreign_pre_chain=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ExtraAdder(allow=REQUEST_LOG_FIELDS),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            # The constitution names the log text "message", structlog says "event".
            structlog.processors.EventRenamer("message"),
            renderer,
        ],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    verbose = logging.getLevelNamesMapping()[level.upper()] <= logging.DEBUG
    for name in STEP_BY_STEP_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET if verbose else logging.WARNING)

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def bind_correlation(
    *, request_id: str | None = None, job_id: str | None = None
) -> None:
    """Attach correlation ids to every record emitted in the current context.

    Args:
        request_id: Id of the HTTP request, or of the request that created a job.
        job_id: Id of the ingestion job being processed.
    """
    values = {"request_id": request_id, "job_id": job_id}
    structlog.contextvars.bind_contextvars(
        **{name: value for name, value in values.items() if value is not None}
    )


def clear_correlation() -> None:
    """Remove every correlation id bound in the current context."""
    structlog.contextvars.clear_contextvars()
