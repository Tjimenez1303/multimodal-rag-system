"""Real PostgreSQL 18 and Qdrant 1.19 containers for integration tests.

Every test under this directory is marked ``integration`` and shares one container of
each service per session. The database is migrated with Alembic exactly as in
production, so the tests also prove that the migrations apply cleanly.
"""

import logging
import os
import shlex
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from huggingface_hub import hf_hub_download
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.qdrant import QdrantContainer

from multimodal_rag.adapters.postgres.tables import metadata
from tests.integration.model_apis import MODELS_URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:18"
QDRANT_IMAGE = "qdrant/qdrant:v1.19.1"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test in this directory as an integration test."""
    for item in items:
        if Path(item.path).is_relative_to(Path(__file__).parent):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start PostgreSQL, apply every migration and yield its asyncpg URL."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine on a database emptied before each test."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        tables = ", ".join(table.name for table in reversed(metadata.sorted_tables))
        await connection.execute(sa.text(f"TRUNCATE {tables} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Start Qdrant and yield its REST URL."""
    with QdrantContainer(QDRANT_IMAGE) as qdrant:
        yield f"http://{qdrant.rest_host_address}"


@pytest.fixture(scope="session")
def embedder_tokenizer_path() -> Path:
    """The embedding tokenizer from EMBEDDER_TOKENIZER_PATH, or downloaded like the
    image downloads it, from the repository and revision in embedder_tokenizer.txt.
    """
    configured = os.environ.get("EMBEDDER_TOKENIZER_PATH")
    if configured:
        return Path(configured)
    repo, filename, _, revision = shlex.split(
        (BACKEND_ROOT / "embedder_tokenizer.txt").read_text()
    )
    return Path(hf_hub_download(repo, filename, revision=revision))


@pytest.fixture
def worker_env(
    database_url: str,
    qdrant_url: str,
    embedder_tokenizer_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Set the environment of the worker and the API, and yield the values set.

    The models point at ``MODELS_URL``, answered by respx, and the Qdrant collection
    is new for each test, so tests never see each other's points. Worker
    subprocesses inherit the same environment.
    """
    values = {
        "DATABASE_URL": database_url,
        "BLOB_ROOT": str(tmp_path / "blobs"),
        "QDRANT_URL": qdrant_url,
        "QDRANT_COLLECTION": f"units_{uuid.uuid4().hex}",
        "VLM_URL": MODELS_URL,
        "VLM_MODEL": "vision",
        "EMBEDDER_URL": MODELS_URL,
        "EMBEDDER_MODEL": "embedder",
        "EMBEDDER_TOKENIZER_PATH": str(embedder_tokenizer_path),
        "ANSWER_MODEL_URL": MODELS_URL,
        "ANSWER_MODEL": "answerer",
        "LIVENESS_FILE": str(tmp_path / "alive"),
        "POLL_SECONDS": "0.2",
        "EXTRACTION_THREADS": "2",
        "LOG_FORMAT": "console",
    }
    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    if artifacts:
        values["DOCLING_ARTIFACTS_PATH"] = artifacts
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    yield values
    # An in-process worker configures logging, which must not leak into later tests.
    logging.getLogger().handlers = []
