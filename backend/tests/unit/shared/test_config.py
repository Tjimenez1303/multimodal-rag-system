from pathlib import Path

import pytest

from multimodal_rag.shared.config import ApiSettings, WorkerSettings
from multimodal_rag.shared.errors import ConfigurationError

DATABASE_URL = "postgresql+asyncpg://rag:secret@localhost:5432/rag"

MODELS_URL = "http://model-runner.docker.internal/engines/v1/"
PROVIDER_ENV = {
    "DATABASE_URL": DATABASE_URL,
    "BLOB_ROOT": "/data/blobs",
    "QDRANT_URL": "http://qdrant:6333",
    "EMBEDDER_URL": MODELS_URL,
    "EMBEDDER_MODEL": "ai/qwen3-embedding:0.6b",
}
API_ENV = PROVIDER_ENV | {
    "ANSWER_MODEL_URL": MODELS_URL,
    "ANSWER_MODEL": "ai/qwen3.5:9b",
}
WORKER_ENV = PROVIDER_ENV | {
    "VLM_URL": MODELS_URL,
    "VLM_MODEL": "ai/qwen3.5:9b",
    "EMBEDDER_TOKENIZER_PATH": "/opt/tokenizers/embedder/tokenizer.json",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in API_ENV | WORKER_ENV:
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


def test_api_settings_expose_the_documented_answering_defaults(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, API_ENV)

    settings = ApiSettings.load()

    assert settings.answer_model == "ai/qwen3.5:9b"
    assert str(settings.answer_model_url) == MODELS_URL
    assert settings.answer_model_timeout_seconds == 60
    assert settings.answer_max_tokens == 800
    assert settings.answer_temperature == 0
    assert settings.retrieval_top_k == 8
    assert settings.min_similarity == 0.60
    assert settings.low_confidence_threshold == 0.90
    assert settings.max_question_chars == 2000
    assert settings.max_filter_documents == 20
    assert settings.answer_concurrency == 2
    assert settings.answer_queue_limit == 6
    assert settings.answer_deadline_seconds == 90
    assert settings.embedder_query_instruction == (
        "Given a question about a technical manual, "
        "retrieve the passages that answer it"
    )
    assert settings.qdrant_collection == "retrieval_units"
    assert settings.provider_retry_attempts == 4
    assert settings.attribution_min_score == 0.5
    assert settings.embedder_batch_size == 32


def test_the_api_requires_the_answer_model_and_the_search_services(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, {"DATABASE_URL": DATABASE_URL, "BLOB_ROOT": "/data/blobs"})

    with pytest.raises(ConfigurationError) as raised:
        ApiSettings.load()

    message = str(raised.value)
    for name in (
        "ANSWER_MODEL_URL",
        "ANSWER_MODEL",
        "QDRANT_URL",
        "EMBEDDER_URL",
        "EMBEDDER_MODEL",
    ):
        assert name in message


def test_the_answer_model_timeout_must_be_shorter_than_the_deadline(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(
        clean_env,
        API_ENV
        | {"ANSWER_MODEL_TIMEOUT_SECONDS": "90", "ANSWER_DEADLINE_SECONDS": "90"},
    )

    with pytest.raises(ConfigurationError, match="ANSWER_MODEL_TIMEOUT_SECONDS"):
        ApiSettings.load()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MIN_SIMILARITY", "1.1"),
        ("LOW_CONFIDENCE_THRESHOLD", "-0.1"),
        ("ANSWER_TEMPERATURE", "2.5"),
        ("ANSWER_QUEUE_LIMIT", "-1"),
        ("ATTRIBUTION_MIN_SCORE", "1.5"),
    ],
)
def test_answering_bounds_are_enforced(
    clean_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    set_env(clean_env, API_ENV | {name: value})

    with pytest.raises(ConfigurationError, match=name):
        ApiSettings.load()


def test_an_empty_waiting_line_is_allowed(clean_env: pytest.MonkeyPatch) -> None:
    set_env(clean_env, API_ENV | {"ANSWER_QUEUE_LIMIT": "0"})

    assert ApiSettings.load().answer_queue_limit == 0


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
    assert settings.embedder_dimensions == 1024
    assert settings.embedder_batch_size == 32
    assert settings.embedder_max_input_tokens == 2048
    assert settings.embedder_tokenizer_path == Path(
        "/opt/tokenizers/embedder/tokenizer.json"
    )


def test_missing_required_variables_are_named_in_the_error(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(clean_env, {"BLOB_ROOT": "/data/blobs"})

    with pytest.raises(ConfigurationError) as raised:
        WorkerSettings.load()

    message = str(raised.value)
    for name in (
        "DATABASE_URL",
        "QDRANT_URL",
        "VLM_URL",
        "EMBEDDER_MODEL",
        "EMBEDDER_TOKENIZER_PATH",
    ):
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


def test_the_embedding_input_must_leave_room_for_a_whole_unit(
    clean_env: pytest.MonkeyPatch,
) -> None:
    set_env(
        clean_env,
        WORKER_ENV | {"MAX_UNIT_TOKENS": "480", "EMBEDDER_MAX_INPUT_TOKENS": "400"},
    )

    with pytest.raises(ConfigurationError, match="EMBEDDER_MAX_INPUT_TOKENS"):
        WorkerSettings.load()
