import asyncio
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
from tests.integration.model_apis import route_model_apis
from tests.integration.polling import poll

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def models() -> Iterator[respx.MockRouter]:
    """Answer the model APIs in process and let every other request through.

    Routes match in order, so the last one passes Qdrant calls and, without
    DOCLING_ARTIFACTS_PATH, Docling's model downloads to the network.
    """
    with respx.mock(assert_all_called=False) as router:
        route_model_apis(router)
        router.route().pass_through()
        yield router


@pytest.mark.slow
@pytest.mark.usefixtures("models")
async def test_uploaded_pdf_is_extracted_described_and_indexed(
    worker_env: dict[str, str], engine: AsyncEngine, qdrant_url: str, tmp_path: Path
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
    # The fixture's schematic covers a fifth of the page, so it is described.
    assert (summary["figures_described"], summary["figures_skipped"]) == (1, 0)
    async with engine.connect() as connection:
        stored = await connection.scalar(
            sa.select(sa.func.count()).select_from(extracted_elements)
        )
    # The fixture has no page furniture, so every element is counted once.
    assert stored == summary["text_elements"] + summary["tables"] + summary["images"]
    assert list((tmp_path / "blobs" / "figures").rglob("*.png"))
    qdrant = AsyncQdrantClient(url=qdrant_url)
    points, _ = await qdrant.scroll(worker_env["QDRANT_COLLECTION"], limit=100)
    await qdrant.close()
    assert len(points) == summary["retrieval_units"] > 0
    assert all(point.payload and point.payload["visible"] for point in points)


async def _until_finished(api: httpx.AsyncClient, job_url: str) -> dict[str, Any]:
    async def finished() -> dict[str, Any] | None:
        job: dict[str, Any] = (await api.get(job_url)).json()
        return job if job["status"] in {"completed", "failed"} else None

    async with asyncio.timeout(120):
        return await poll(finished)
