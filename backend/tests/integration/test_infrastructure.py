import asyncio
import logging
import uuid
from datetime import UTC, datetime

import asyncpg
import httpx
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag.adapters.postgres.engine import check_database
from multimodal_rag.adapters.postgres.tables import documents, ingestion_jobs, metadata
from tests.integration.conftest import BACKEND_ROOT


async def test_migrations_produce_exactly_the_declared_schema(
    engine: AsyncEngine,
) -> None:
    def differences(connection: Connection) -> list[object]:
        context = MigrationContext.configure(connection)
        return list(compare_metadata(context, metadata))

    async with engine.connect() as connection:
        diff = await connection.run_sync(differences)

    assert diff == []


async def test_database_probe_succeeds(engine: AsyncEngine) -> None:
    await check_database(engine)


async def test_enqueueing_a_job_notifies_listening_workers(
    engine: AsyncEngine, database_url: str
) -> None:
    listener = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    notified: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    await listener.add_listener(
        "ingestion_jobs", lambda *args: notified.set_result(args[3])
    )
    now = datetime.now(UTC)
    document_id, job_id = uuid.uuid4(), uuid.uuid4()

    async with engine.begin() as connection:
        await connection.execute(
            documents.insert().values(
                id=document_id,
                sha256="b" * 64,
                file_name="manual.pdf",
                size_bytes=10,
                page_count=1,
                blob_key="documents/b.pdf",
                created_at=now,
            )
        )
        await connection.execute(
            ingestion_jobs.insert().values(
                id=job_id,
                document_id=document_id,
                status="pending",
                max_attempts=3,
                correlation_id="req-1",
                created_at=now,
                updated_at=now,
            )
        )

    assert await asyncio.wait_for(notified, timeout=5) == str(job_id)
    await listener.close()


async def test_qdrant_is_ready(qdrant_url: str) -> None:
    async with httpx.AsyncClient(base_url=qdrant_url, timeout=5) as client:
        response = await client.get("/readyz")

    assert response.status_code == 200


def test_running_migrations_keeps_application_loggers_enabled(
    database_url: str,
) -> None:
    application_logger = logging.getLogger("multimodal_rag.migration_probe")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    assert not application_logger.disabled
