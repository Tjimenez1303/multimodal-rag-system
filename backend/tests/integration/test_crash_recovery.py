"""A worker process killed with SIGKILL in the middle of a job (FR-025, SC-008).

The first worker runs the job until it has written its retrieval units and elements,
then waits forever for Qdrant to publish them. It is killed there, leaving the most
partial state an attempt can leave. A second worker must reclaim the job once the
lease expires, run it again from scratch and end with the same content as a clean run
of the same document.
"""

import asyncio
import os
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag import bootstrap
from multimodal_rag.adapters.postgres.tables import extracted_elements
from tests.integration.polling import poll
from tests.integration.worker_process import HOLD_PUBLISH

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND_ROOT / "tests" / "fixtures" / "digital.pdf"
# Long enough for the heartbeat to renew it, short enough to reclaim it quickly.
LEASE_SECONDS = 5
# Docling downloads its models on the first start when no artifacts are configured.
WORKER_START_SECONDS = 300
FINISHED = frozenset({"completed", "failed"})

type _Probe = Callable[[], Awaitable[dict[str, Any] | None]]


class _PointCounter:
    def __init__(self, client: AsyncQdrantClient, collection: str) -> None:
        self._client = client
        self._collection = collection

    async def count(self, document_id: str, *, visible: bool) -> int:
        conditions: list[models.Condition] = [
            models.FieldCondition(
                key="document_id", match=models.MatchValue(value=document_id)
            ),
            models.FieldCondition(
                key="visible", match=models.MatchValue(value=visible)
            ),
        ]
        result = await self._client.count(
            self._collection, count_filter=models.Filter(must=conditions), exact=True
        )
        return result.count


@pytest.fixture
async def points(
    worker_env: dict[str, str], qdrant_url: str
) -> AsyncIterator[_PointCounter]:
    """Counts the points of the test's own collection."""
    client = AsyncQdrantClient(url=qdrant_url)
    yield _PointCounter(client, worker_env["QDRANT_COLLECTION"])
    await client.close()


@pytest.mark.slow
async def test_killed_worker_is_replaced_without_duplicates(
    engine: AsyncEngine, points: _PointCounter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEASE_SECONDS", str(LEASE_SECONDS))
    monkeypatch.setenv("HEARTBEAT_SECONDS", "1")
    async with (
        LifespanManager(bootstrap.create_api_app()) as manager,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://test"
        ) as api,
    ):
        crashed = await _upload(api, "crashed")
        async with _worker(hold_publish=True) as first:
            async with asyncio.timeout(WORKER_START_SECONDS):
                await poll(_units_written(api, engine, crashed, first))
            first.kill()
            assert await first.wait() == -signal.SIGKILL
        left_behind = await points.count(crashed["document_id"], visible=False)

        async with _worker(hold_publish=False) as second:
            async with asyncio.timeout(WORKER_START_SECONDS):
                recovered = await poll(_finished(api, crashed, second))
            clean = await _upload(api, "clean")
            async with asyncio.timeout(WORKER_START_SECONDS):
                reference = await poll(_finished(api, clean, second))

    assert left_behind > 0
    assert (recovered["status"], recovered["attempt"]) == ("completed", 2), recovered
    assert (reference["status"], reference["attempt"]) == ("completed", 1), reference
    units = recovered["summary"]["retrieval_units"]
    assert units == reference["summary"]["retrieval_units"] > 0
    assert await points.count(crashed["document_id"], visible=True) == units
    assert await points.count(crashed["document_id"], visible=False) == 0
    assert await _element_count(engine, crashed["document_id"]) == (
        await _element_count(engine, clean["document_id"])
    )


def _units_written(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    upload: dict[str, Any],
    worker: asyncio.subprocess.Process,
) -> _Probe:
    # Elements are stored after the units are indexed, just before publishing.

    async def probe() -> dict[str, Any] | None:
        job = await _job(api, upload, worker)
        stored = await _element_count(engine, upload["document_id"])
        return job if job["stage"] == "finalizing" and stored > 0 else None

    return probe


def _finished(
    api: httpx.AsyncClient,
    upload: dict[str, Any],
    worker: asyncio.subprocess.Process,
) -> _Probe:

    async def probe() -> dict[str, Any] | None:
        job = await _job(api, upload, worker)
        return job if job["status"] in FINISHED else None

    return probe


async def _job(
    api: httpx.AsyncClient,
    upload: dict[str, Any],
    worker: asyncio.subprocess.Process,
) -> dict[str, Any]:
    # A worker that exits on its own will never move the job, so fail right away.
    if worker.returncode is not None:
        pytest.fail(f"The worker exited with code {worker.returncode}")
    job: dict[str, Any] = (await api.get(f"/api/v1/jobs/{upload['job_id']}")).json()
    return job


async def _upload(api: httpx.AsyncClient, label: str) -> dict[str, Any]:
    # A trailing PDF comment makes each upload a different document.
    content = FIXTURE.read_bytes() + f"%{label}\n".encode()
    response = await api.post(
        "/api/v1/documents", files={"file": (f"{label}.pdf", content)}
    )
    assert response.status_code == 202, response.text
    upload: dict[str, Any] = response.json()
    return upload


@asynccontextmanager
async def _worker(*, hold_publish: bool) -> AsyncIterator[asyncio.subprocess.Process]:
    env = os.environ | {HOLD_PUBLISH: "1" if hold_publish else "0"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.integration.worker_process",
        cwd=BACKEND_ROOT,
        env=env,
    )
    try:
        yield process
    finally:
        # A worker only exits on a signal, so a failing test must not leave it behind.
        if process.returncode is None:
            process.terminate()
            try:
                async with asyncio.timeout(30):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()


async def _element_count(engine: AsyncEngine, document_id: str) -> int:
    async with engine.connect() as connection:
        stored = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(extracted_elements)
            .where(extracted_elements.c.document_id == uuid.UUID(document_id))
        )
    return int(stored or 0)
