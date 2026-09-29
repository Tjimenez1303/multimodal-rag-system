import asyncio
import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag import bootstrap
from multimodal_rag.adapters.postgres.tables import extracted_elements

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# The models are replaced by respx routes, so these hosts are never contacted.
MODELS_URL = "http://models.test/v1/"
COLLECTION = "end_to_end_units"


@pytest.fixture
def worker_env(
    database_url: str,
    qdrant_url: str,
    embedder_tokenizer_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    values = {
        "DATABASE_URL": database_url,
        "BLOB_ROOT": str(tmp_path / "blobs"),
        "QDRANT_URL": qdrant_url,
        "QDRANT_COLLECTION": COLLECTION,
        "VLM_URL": MODELS_URL,
        "VLM_MODEL": "vision",
        "EMBEDDER_URL": MODELS_URL,
        "EMBEDDER_MODEL": "embedder",
        "EMBEDDER_TOKENIZER_PATH": str(embedder_tokenizer_path),
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
    yield
    logging.getLogger().handlers = []


@pytest.fixture
def models() -> Iterator[respx.MockRouter]:
    """Answer the model APIs in process and let every other request through.

    Routes match in order, so the last one passes Qdrant calls and, without
    DOCLING_ARTIFACTS_PATH, Docling's model downloads to the network.
    """

    def embeddings(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [
            {"index": n, "embedding": [float(len(text) % 7 + 1)] * 1024}
            for n, text in enumerate(texts)
        ]
        return httpx.Response(200, json={"data": data})

    with respx.mock(assert_all_called=False) as router:
        router.post(f"{MODELS_URL}embeddings").mock(side_effect=embeddings)
        router.post(f"{MODELS_URL}chat/completions").respond(
            json={"choices": [{"message": {"content": "A magneto wired to V-12."}}]}
        )
        router.route().pass_through()
        yield router


@pytest.mark.slow
@pytest.mark.usefixtures("models")
async def test_uploaded_pdf_is_extracted_described_and_indexed(
    worker_env: None, engine: AsyncEngine, qdrant_url: str, tmp_path: Path
) -> None:
    stop = asyncio.Event()
    # AsyncClient over ASGITransport, with LifespanManager because the app builds
    # its use cases in the lifespan.
    async with (
        LifespanManager(bootstrap.create_api_app()) as manager,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://test"
        ) as api,
    ):
        upload = await api.post(
            "/api/v1/documents",
            files={"file": ("digital.pdf", (FIXTURES / "digital.pdf").read_bytes())},
        )
        worker = asyncio.create_task(bootstrap.run_worker(stop=stop))
        job = await _until_finished(api, upload.headers["location"])
        stop.set()
        await asyncio.wait_for(worker, timeout=30)

    assert job["status"] == "completed", job
    assert job["attempt"] == 1
    summary = job["summary"]
    assert (summary["pages"], summary["tables"], summary["images"]) == (1, 1, 1)
    # Docling crops the fixture's drawing to its 328 x 45 pt band, 3% of the page,
    # below the 5% a figure needs to be described.
    assert (summary["figures_described"], summary["figures_skipped"]) == (0, 1)
    async with engine.connect() as connection:
        stored = await connection.scalar(
            sa.select(sa.func.count()).select_from(extracted_elements)
        )
    # The fixture has no page furniture, so every element is counted once.
    assert stored == summary["text_elements"] + summary["tables"] + summary["images"]
    assert list((tmp_path / "blobs" / "figures").rglob("*.png"))
    qdrant = AsyncQdrantClient(url=qdrant_url)
    points, _ = await qdrant.scroll(COLLECTION, limit=100)
    await qdrant.close()
    assert len(points) == summary["retrieval_units"] > 0
    assert all(point.payload and point.payload["visible"] for point in points)


async def _until_finished(api: httpx.AsyncClient, job_url: str) -> dict[str, Any]:
    async with asyncio.timeout(120):
        while True:
            job: dict[str, Any] = (await api.get(job_url)).json()
            if job["status"] in {"completed", "failed"}:
                return job
            await asyncio.sleep(0.2)
