"""Database connectivity: engines with explicit timeouts and the readiness probe."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from multimodal_rag.shared.config import DatabaseSettings


def connect_args(settings: DatabaseSettings) -> dict[str, Any]:
    """Return the asyncpg options that bound every connection and statement.

    Args:
        settings: Database timeouts.

    Returns:
        Keyword arguments passed to ``asyncpg.connect``.
    """
    return {
        "timeout": settings.db_connect_timeout_seconds,
        "command_timeout": settings.db_statement_timeout_ms / 1000,
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "application_name": "multimodal-rag",
        },
    }


def engine_options(settings: DatabaseSettings) -> dict[str, Any]:
    """Return the pool and driver options of a long-running process.

    Connection attempts, statements and waits for a pooled connection all have an
    explicit timeout (constitution Principle VI). Connections are checked before use so
    a restarted database does not surface as an error on the first request.

    Args:
        settings: Pool size and timeouts.

    Returns:
        Keyword arguments for ``create_async_engine``.
    """
    return {
        "pool_size": settings.db_pool_size,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_pre_ping": True,
        "connect_args": connect_args(settings),
    }


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build the pooled engine used by every repository of one process.

    Args:
        settings: Database URL, pool size and timeouts.

    Returns:
        A lazily connecting async engine.
    """
    return create_async_engine(settings.database_url, **engine_options(settings))


def create_migration_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build the engine of a one-shot command such as ``alembic upgrade``.

    It keeps the connection and statement timeouts but pools nothing, as in Alembic's
    async template, because the command opens one connection and exits.

    Args:
        settings: Database URL and timeouts.

    Returns:
        A lazily connecting async engine without a pool.
    """
    return create_async_engine(
        settings.database_url, poolclass=NullPool, connect_args=connect_args(settings)
    )


async def check_database(engine: AsyncEngine) -> None:
    """Run a trivial query to prove the database accepts connections.

    Args:
        engine: Engine of the current process.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: If the database cannot be reached.
    """
    async with engine.connect() as connection:
        await connection.execute(sa.text("SELECT 1"))
