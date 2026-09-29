import asyncio
import io
import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi.testclient import TestClient
from tokenizers import Tokenizer
from tokenizers.models import WordLevel

from multimodal_rag import bootstrap
from multimodal_rag.__main__ import main
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.shared.errors import ConfigurationError
from multimodal_rag.shared.logging import configure_logging

WORKER_ENV = {
    "QDRANT_URL": "http://qdrant:6333",
    "VLM_URL": "http://model-runner.docker.internal/engines/v1/",
    "VLM_MODEL": "ai/qwen3.5:9b",
    "EMBEDDER_URL": "http://model-runner.docker.internal/engines/v1/",
    "EMBEDDER_MODEL": "ai/qwen3-embedding:0.6b",
    "EMBEDDER_TOKENIZER_PATH": "/opt/tokenizers/embedder/tokenizer.json",
}
# The API connects to none of these at startup, so unreachable hosts are enough.
ANSWERING_ENV = {
    "QDRANT_URL": "http://127.0.0.1:9",
    "EMBEDDER_URL": "http://127.0.0.1:9/v1/",
    "EMBEDDER_MODEL": "ai/qwen3-embedding:0.6b",
    "ANSWER_MODEL_URL": "http://127.0.0.1:9/v1/",
    "ANSWER_MODEL": "ai/qwen3.5:9b",
    "RERANKER_URL": "http://127.0.0.1:9/v1/",
    "RERANKER_MODEL": "ai/qwen3-reranker:0.6B",
}


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    # Port 1 on localhost refuses connections at once, so readiness fails fast.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://rag:x@127.0.0.1:1/rag")
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path))
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("LOG_FORMAT", "console")
    for name, value in ANSWERING_ENV.items():
        monkeypatch.setenv(name, value)
    tokenizer = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]")).save(str(tokenizer))
    monkeypatch.setenv("EMBEDDER_TOKENIZER_PATH", str(tokenizer))
    return monkeypatch


@pytest.fixture(autouse=True)
def reset_root_logger() -> Iterator[None]:
    yield
    logging.getLogger().handlers = []


def test_api_is_served_behind_the_request_id_middleware(
    api_env: pytest.MonkeyPatch,
) -> None:
    assert isinstance(bootstrap.create_api_app(), RequestContextMiddleware)


def test_api_reports_liveness_and_an_unreachable_database(
    api_env: pytest.MonkeyPatch,
) -> None:
    with TestClient(bootstrap.create_api_app()) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["detail"] == "Unavailable: database"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/jobs/7f9d1c3e-0b1a-4c55-9a3e-6f0f6a8e2b11",
        "/api/v1/documents/7f9d1c3e-0b1a-4c55-9a3e-6f0f6a8e2b11/elements",
        "/api/v1/documents/7f9d1c3e-0b1a-4c55-9a3e-6f0f6a8e2b11/images/"
        "0b1a7f9d-1c3e-4c55-9a3e-6f0f6a8e2b11",
    ],
)
def test_api_answers_503_while_the_database_is_unreachable(
    api_env: pytest.MonkeyPatch, path: str
) -> None:
    with TestClient(bootstrap.create_api_app()) as client:
        response = client.get(path)

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"


class RecordingClient(httpx.AsyncClient):
    """An httpx client that records every instance created."""

    created: ClassVar[list[httpx.AsyncClient]] = []

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        RecordingClient.created.append(self)


async def test_answering_clients_live_only_inside_the_lifespan(
    api_env: pytest.MonkeyPatch,
) -> None:
    RecordingClient.created = []
    api_env.setattr(httpx, "AsyncClient", RecordingClient)
    app = bootstrap.create_api_app()
    assert RecordingClient.created == []

    async with LifespanManager(app):
        opened = list(RecordingClient.created)
        assert len(opened) == 3
        assert not any(client.is_closed for client in opened)

    assert all(client.is_closed for client in opened)


def test_questions_are_served_and_fail_while_search_is_unreachable(
    api_env: pytest.MonkeyPatch,
) -> None:
    api_env.setenv("PROVIDER_RETRY_ATTEMPTS", "1")

    with TestClient(bootstrap.create_api_app()) as client:
        response = client.post("/api/v1/questions", json={"question": "What is V-12?"})

    assert response.status_code == 503
    assert response.json()["code"] == "search_unavailable"


@pytest.mark.parametrize(
    "name", ["ANSWER_MODEL_URL", "RERANKER_URL", "QDRANT_URL", "EMBEDDER_MODEL"]
)
def test_api_refuses_to_start_without_the_answering_settings(
    api_env: pytest.MonkeyPatch, name: str
) -> None:
    api_env.delenv(name)

    with pytest.raises(ConfigurationError, match=name):
        bootstrap.create_api_app()


def test_api_refuses_to_start_without_the_reranker_tokenizer(
    api_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    api_env.setenv("EMBEDDER_TOKENIZER_PATH", str(tmp_path / "missing.json"))

    with (
        pytest.raises(ConfigurationError, match="missing.json"),
        TestClient(bootstrap.create_api_app()),
    ):
        pass


def test_api_refuses_to_start_without_required_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BLOB_ROOT", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        bootstrap.create_api_app()


async def test_worker_logs_readiness_and_stops_on_request(
    api_env: pytest.MonkeyPatch,
) -> None:
    for name, value in WORKER_ENV.items():
        api_env.setenv(name, value)
    api_env.setenv("LOG_FORMAT", "json")
    stop = asyncio.Event()
    stop.set()

    stream = io.StringIO()

    def configure_to_stream(**kwargs: Any) -> None:
        configure_logging(**kwargs, stream=stream)

    api_env.setattr("multimodal_rag.bootstrap.configure_logging", configure_to_stream)
    await bootstrap.run_worker(stop=stop)

    events = [json.loads(line)["message"] for line in stream.getvalue().splitlines()]
    assert events[0].startswith("worker starting")
    assert "ai/qwen3.5:9b" in events[0]
    assert events[-1] == "worker stopped"


def test_main_serves_the_api_with_uvicorn_and_json_logging(
    api_env: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def record_run(app: str, **options: Any) -> None:
        calls.append({"app": app, **options})

    api_env.setattr("multimodal_rag.__main__.uvicorn.run", record_run)

    main(["api"])

    [call] = calls
    assert call["app"] == "multimodal_rag.bootstrap:create_api_app"
    assert call["factory"] is True
    assert call["log_config"] is None
    assert call["access_log"] is False
    assert (call["host"], call["port"]) == ("0.0.0.0", 8000)


def test_main_rejects_unknown_roles() -> None:
    with pytest.raises(SystemExit):
        main(["scheduler"])


@pytest.fixture
def worker_env(api_env: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name, value in WORKER_ENV.items():
        api_env.setenv(name, value)
    liveness = tmp_path / "alive"
    api_env.setenv("LIVENESS_FILE", str(liveness))
    api_env.setenv("LIVENESS_MAX_AGE_SECONDS", "30")
    return liveness


def test_worker_health_passes_while_the_liveness_file_is_fresh(
    worker_env: Path,
) -> None:
    worker_env.touch()

    with pytest.raises(SystemExit) as exit_info:
        main(["worker-health"])

    assert exit_info.value.code == 0


@pytest.mark.parametrize("age_seconds", [None, 31])
def test_worker_health_fails_when_the_liveness_file_is_stale_or_missing(
    worker_env: Path, age_seconds: int | None
) -> None:
    if age_seconds is not None:
        worker_env.touch()
        stale = time.time() - age_seconds
        os.utime(worker_env, (stale, stale))

    with pytest.raises(SystemExit) as exit_info:
        main(["worker-health"])

    assert exit_info.value.code == 1
