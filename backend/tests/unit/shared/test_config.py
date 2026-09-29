from pathlib import Path

import pytest

from multimodal_rag.shared.config import ApiSettings, WorkerSettings
from multimodal_rag.shared.errors import ConfigurationError

DATABASE_URL = "postgresql+asyncpg://rag:secret@localhost:5432/rag"

API_ENV = {"DATABASE_URL": DATABASE_URL, "BLOB_ROOT": "/data/blobs"}
WORKER_ENV = API_ENV | {
    "QDRANT_URL": "http://qdrant:6333",
    "VLM_URL": "http://model-runner.docker.internal/engines/v1/",
    "VLM_MODEL": "ai/qwen3.5:9b",
    "EMBEDDER_URL": "http://model-runner.docker.internal/engines/v1/",
    "EMBEDDER_MODEL": "ai/qwen3-embedding:0.6b",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in WORKER_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_api_settings_load_required_values_and_defaults(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, API_ENV)

    settings = ApiSettings.load()

    assert settings.database_url == DATABASE_URL
    assert settings.blob_root == Path("/data/blobs")
    assert settings.max_upload_bytes == 200 * 1024 * 1024
    assert settings.max_upload_pages == 500
    assert settings.max_attempts == 3
    assert settings.log_format == "json"


def test_worker_settings_expose_documented_defaults(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, WORKER_ENV)

    settings = WorkerSettings.load()

    assert settings.vlm_model == "ai/qwen3.5:9b"
    assert settings.extraction_page_batch == 4
    assert settings.figure_concurrency == 2
    assert settings.max_unit_tokens == 480
    assert settings.decorative_min_pages == 3
    assert settings.decorative_min_page_share == 0.2
    assert settings.near_text_max_points == 72.0
    assert settings.qdrant_timeout_seconds == 10.0


def test_missing_required_variables_are_named_in_the_error(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, {"BLOB_ROOT": "/data/blobs"})

    with pytest.raises(ConfigurationError) as raised:
        WorkerSettings.load()

    message = str(raised.value)
    for name in ("DATABASE_URL", "QDRANT_URL", "VLM_URL", "EMBEDDER_MODEL"):
        assert name in message


def test_database_url_must_use_the_asyncpg_driver(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, API_ENV | {"DATABASE_URL": "postgresql://rag@localhost/rag"})

    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        ApiSettings.load()


def test_heartbeat_must_be_shorter_than_the_lease(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, WORKER_ENV | {"LEASE_SECONDS": "30", "HEARTBEAT_SECONDS": "30"})

    with pytest.raises(ConfigurationError, match="HEARTBEAT_SECONDS"):
        WorkerSettings.load()


def test_liveness_interval_must_be_shorter_than_its_maximum_age(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(
        clean_env,
        WORKER_ENV
        | {"LIVENESS_INTERVAL_SECONDS": "60", "LIVENESS_MAX_AGE_SECONDS": "60"},
    )

    with pytest.raises(ConfigurationError, match="LIVENESS_INTERVAL_SECONDS"):
        WorkerSettings.load()
