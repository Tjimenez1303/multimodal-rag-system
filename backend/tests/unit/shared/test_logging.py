import io
import json
import logging
from collections.abc import Iterator

import pytest

from multimodal_rag.shared.logging import (
    bind_correlation,
    clear_correlation,
    configure_logging,
)


@pytest.fixture(autouse=True)
def isolated_context() -> Iterator[None]:
    clear_correlation()
    yield
    clear_correlation()
    logging.getLogger().handlers = []


def records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_records_carry_correlation_ids_and_render_lazy_arguments() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", stream=stream)
    bind_correlation(request_id="req-1", job_id="job-7")

    logging.getLogger("multimodal_rag.test").info("claimed job %s", "job-7")

    [record] = records(stream)
    assert record["message"] == "claimed job job-7"
    assert record["request_id"] == "req-1"
    assert record["job_id"] == "job-7"
    assert record["level"] == "info"
    assert record["logger"] == "multimodal_rag.test"
    assert "timestamp" in record


def test_cleared_correlation_is_absent_from_later_records() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", stream=stream)
    bind_correlation(job_id="job-7")
    clear_correlation()

    logging.getLogger("multimodal_rag.test").info("idle")

    [record] = records(stream)
    assert "job_id" not in record


def test_records_below_the_configured_level_are_dropped() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", level="WARNING", stream=stream)

    logging.getLogger("multimodal_rag.test").info("hidden")
    logging.getLogger("multimodal_rag.test").warning("shown")

    assert [record["message"] for record in records(stream)] == ["shown"]


def test_step_by_step_library_logs_are_hidden_at_info() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", level="INFO", stream=stream)

    logging.getLogger("docling.document_converter").info("converting batch")
    logging.getLogger("docling.document_converter").warning("page skipped")
    logging.getLogger("multimodal_rag.test").info("job completed")

    assert [record["message"] for record in records(stream)] == [
        "page skipped",
        "job completed",
    ]


def test_debug_level_shows_step_by_step_library_logs() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", level="DEBUG", stream=stream)

    logging.getLogger("docling.document_converter").info("converting batch")

    assert [record["message"] for record in records(stream)] == ["converting batch"]


def test_exceptions_are_rendered_in_the_json_record() -> None:
    stream = io.StringIO()
    configure_logging(log_format="json", stream=stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("multimodal_rag.test").exception("failed")

    [record] = records(stream)
    assert "RuntimeError: boom" in str(record["exception"])


def test_console_format_renders_readable_lines() -> None:
    stream = io.StringIO()
    configure_logging(log_format="console", stream=stream)

    logging.getLogger("multimodal_rag.test").info("ready on port %s", 8000)

    assert "ready on port 8000" in stream.getvalue()
