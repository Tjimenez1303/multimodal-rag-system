"""Alembic environment that migrates the database with the async engine.

Settings come from the same pydantic-settings class as the rest of the database layer,
so migrations use the same URL, connection timeout and logging format. Tests may pass
the URL through the ``sqlalchemy.url`` option instead of the environment.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from multimodal_rag.adapters.postgres.engine import create_migration_engine
from multimodal_rag.adapters.postgres.tables import metadata
from multimodal_rag.shared.config import DatabaseSettings
from multimodal_rag.shared.logging import configure_logging

config = context.config


def _settings() -> DatabaseSettings:
    url_override = config.get_main_option("sqlalchemy.url")
    if url_override:
        return DatabaseSettings(database_url=url_override)
    return DatabaseSettings.load()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations(settings: DatabaseSettings) -> None:
    engine = create_migration_engine(settings)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


settings = _settings()
# Only the alembic command line configures logging. Called from Python, as in tests,
# migrations leave the caller's logging untouched.
if config.cmd_opts is not None:
    configure_logging(log_format=settings.log_format, level=settings.log_level)

if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async_migrations(settings))
