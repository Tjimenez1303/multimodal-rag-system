"""Database connectivity: engines, connections and the readiness probe.

Every connection has explicit timeouts. Repositories open connections through
``connect`` and ``transaction``, which turn outages and timeouts into
``StorageUnavailableError`` or ``StorageTimeoutError``, answered with 503 by the API.
Any other database error is a defect, such as a missing table or a broken constraint,
and propagates unchanged as an internal error. asyncpg raises a refused connection as
a plain ``OSError`` that SQLAlchemy does not wrap, so the translation surrounds every
connection instead of living in an engine event.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from multimodal_rag.shared.config import DatabaseSettings
from multimodal_rag.shared.errors import (
    StorageError,
    StorageTimeoutError,
    StorageUnavailableError,
)

_CLIENT_TIMEOUT_MARGIN_SECONDS = 1.0


def connect_args(settings: DatabaseSettings) -> dict[str, Any]:
    """Return the asyncpg options that bound every connection and statement.

    Args:
        settings: Database timeouts.

    Returns:
        Keyword arguments passed to ``asyncpg.connect``.
    """
    return {
        "timeout": settings.db_connect_timeout_seconds,
        # The client guard fires after the server's statement_timeout, so PostgreSQL
        # cancels first with SQLSTATE 57014 and the error reads as a timeout.
        "command_timeout": settings.db_statement_timeout_ms / 1000
        + _CLIENT_TIMEOUT_MARGIN_SECONDS,
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

    It keeps the connection and statement timeouts but pools nothing, because the
    command opens one connection and exits.

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


# PostgreSQL SQLSTATE of a statement cancelled by statement_timeout.
_QUERY_CANCELED = "57014"
# Transient conditions (PostgreSQL appendix A): connection exceptions (class 08),
# insufficient resources such as too many connections (class 53), server shutdown or
# start-up (57P0x), and a serialization failure or deadlock whose retry can succeed.
_UNAVAILABLE_PREFIXES = ("08", "53", "57P", "40001", "40P01")


@contextmanager
def translated_errors() -> Iterator[None]:
    """Raise storage errors for database outages and timeouts inside the block.

    Yields:
        Nothing. The block runs with the translation in place.

    Raises:
        StorageUnavailableError: If the database cannot be reached or the connection
            was lost.
        StorageTimeoutError: If a statement or the wait for a pooled connection timed
            out.
    """
    try:
        yield
    except sa_exc.TimeoutError as error:
        # No pooled connection was free within pool_timeout
        raise StorageTimeoutError("No database connection was free in time") from error
    except sa_exc.DBAPIError as error:
        # Driver errors become storage errors when they mean an outage or a timeout
        translated = _translate(error)
        if translated is None:
            raise
        raise translated from error
    except OSError as error:
        # The host cannot be reached at all
        raise StorageUnavailableError("The database cannot be reached") from error


@asynccontextmanager
async def transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Open a connection in a transaction that commits when the block ends.

    Args:
        engine: Engine of the current process.

    Yields:
        The connection.

    Raises:
        StorageUnavailableError: If the database is unreachable.
        StorageTimeoutError: If the database does not answer in time.
    """
    with translated_errors():
        async with engine.begin() as connection:
            yield connection


@asynccontextmanager
async def connect(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Open a connection for reads.

    Args:
        engine: Engine of the current process.

    Yields:
        The connection.

    Raises:
        StorageUnavailableError: If the database is unreachable.
        StorageTimeoutError: If the database does not answer in time.
    """
    with translated_errors():
        async with engine.connect() as opened:
            yield opened


def _translate(error: sa_exc.DBAPIError) -> StorageError | None:
    # Classify the error by its PostgreSQL SQLSTATE code
    if error.connection_invalidated:
        return StorageUnavailableError("The database connection was lost")
    sqlstate = getattr(error.orig, "sqlstate", None) or ""
    if sqlstate == _QUERY_CANCELED:
        return StorageTimeoutError("A database statement timed out")
    if sqlstate.startswith(_UNAVAILABLE_PREFIXES):
        return StorageUnavailableError("The database is not accepting connections")
    return None
