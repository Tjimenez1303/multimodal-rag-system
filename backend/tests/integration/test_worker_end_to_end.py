import asyncio
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag import bootstrap
from multimodal_rag.adapters.postgres.tables import extracted_elements

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def worker_env(
    database_url: str,
    qdrant_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    values = {
        "DATABASE_URL": database_url,
        "BLOB_ROOT": str(tmp_path / "blobs"),
        "QDRANT_URL": qdrant_url,
        "VLM_URL": "http://127.0.0.1:9/v1",
        "VLM_MODEL": "unused",
        "EMBEDDER_URL": "http://127.0.0.1:9/v1",
        "EMBEDDER_MODEL": "unused",
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


@pytest.mark.slow
async def test_uploaded_pdf_is_processed_by_the_worker(
    worker_env: None, engine: AsyncEngine, tmp_path: Path
) -> None:
    stop = asyncio.Event()
    # FastAPI's async testing guide: AsyncClient over ASGITransport, with
    # LifespanManager because the app builds its use cases in the lifespan.
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
    async with engine.connect() as connection:
        stored = await connection.scalar(
            sa.select(sa.func.count()).select_from(extracted_elements)
        )
    # The fixture has no page furniture, so every element is counted once.
    assert stored == summary["text_elements"] + summary["tables"] + summary["images"]
    assert list((tmp_path / "blobs" / "figures").rglob("*.png"))


async def _until_finished(api: httpx.AsyncClient, job_url: str) -> dict[str, Any]:
    async with asyncio.timeout(120):
        while True:
            job: dict[str, Any] = (await api.get(job_url)).json()
            if job["status"] in {"completed", "failed"}:
                return job
            await asyncio.sleep(0.2)
