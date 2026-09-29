import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag.adapters.postgres.documents import PostgresDocumentRepository
from multimodal_rag.adapters.postgres.job_notifications import PostgresJobNotifications
from multimodal_rag.adapters.postgres.job_queue import PostgresJobQueue
from multimodal_rag.ingestion.domain import Document, IngestionJob
from tests.fakes import FrozenClock


@pytest.fixture
async def notifications(database_url: str) -> AsyncIterator[PostgresJobNotifications]:
    listener = PostgresJobNotifications(database_url, timeout_seconds=5)
    yield listener
    await listener.close()


async def enqueue_one(engine: AsyncEngine) -> None:
    clock = FrozenClock()
    sha256 = uuid.uuid4().hex * 2
    document, _ = await PostgresDocumentRepository(engine).register(
        Document(
            id=uuid.uuid4(),
            sha256=sha256,
            file_name="m.pdf",
            size_bytes=1,
            page_count=1,
            blob_key=Document.blob_key_for(sha256),
            created_at=clock.now(),
        )
    )
    await PostgresJobQueue(engine).enqueue(
        IngestionJob.create(
            job_id=uuid.uuid4(),
            document_id=document.id,
            max_attempts=3,
            correlation_id="req-1",
            now=clock.now(),
        )
    )


async def timed_wait(listener: PostgresJobNotifications, seconds: float) -> float:
    started = time.perf_counter()
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(seconds):
            await listener.wait()
    return time.perf_counter() - started


async def test_wait_ends_as_soon_as_a_job_is_enqueued(
    engine: AsyncEngine, notifications: PostgresJobNotifications
) -> None:
    await timed_wait(notifications, 5)
    waiting = asyncio.create_task(timed_wait(notifications, 10))
    await asyncio.sleep(0.2)

    await enqueue_one(engine)

    assert await asyncio.wait_for(waiting, timeout=5) < 5


async def test_first_wait_after_connecting_returns_at_once(
    notifications: PostgresJobNotifications,
) -> None:
    assert await timed_wait(notifications, 5) < 1


async def test_wait_falls_back_to_the_poll_interval(
    notifications: PostgresJobNotifications,
) -> None:
    await timed_wait(notifications, 5)

    assert 0.2 <= await timed_wait(notifications, 0.3) < 2


async def test_listener_reconnects_after_its_connection_is_killed(
    engine: AsyncEngine, notifications: PostgresJobNotifications
) -> None:
    await timed_wait(notifications, 5)
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
            )
        )
    await asyncio.sleep(0.2)
    await timed_wait(notifications, 5)
    waiting = asyncio.create_task(timed_wait(notifications, 10))
    await asyncio.sleep(0.2)

    await enqueue_one(engine)

    assert await asyncio.wait_for(waiting, timeout=5) < 5


async def test_unreachable_database_degrades_to_polling() -> None:
    listener = PostgresJobNotifications(
        "postgresql+asyncpg://rag:x@127.0.0.1:1/rag", timeout_seconds=1
    )

    assert await timed_wait(listener, 0.2) < 2
    await listener.close()


async def test_closing_after_the_connection_was_killed_does_not_raise(
    engine: AsyncEngine, notifications: PostgresJobNotifications
) -> None:
    await timed_wait(notifications, 5)
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
            )
        )

    await notifications.close()


async def test_a_listener_that_cannot_subscribe_leaks_no_connection(
    engine: AsyncEngine, database_url: str
) -> None:
    # An empty channel name is a syntax error for LISTEN, so subscribing fails
    # after the connection was opened.
    broken = PostgresJobNotifications(database_url, timeout_seconds=5, channel="")

    async def client_connections() -> int:
        async with engine.connect() as connection:
            count: int = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE backend_type = 'client backend'"
                )
            )
        return count

    before = await client_connections()
    for _ in range(3):
        await timed_wait(broken, 0.2)
    await asyncio.sleep(0.2)

    assert await client_connections() == before
    await broken.close()
