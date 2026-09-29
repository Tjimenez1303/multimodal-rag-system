import pytest
import sqlalchemy.exc as sa_exc

from multimodal_rag.adapters.postgres.engine import (
    connect_args,
    create_engine,
    create_migration_engine,
    engine_options,
    translated_errors,
)
from multimodal_rag.ingestion.errors import LeaseLostError
from multimodal_rag.shared.config import DatabaseSettings
from multimodal_rag.shared.errors import StorageTimeoutError, StorageUnavailableError

SETTINGS = DatabaseSettings(
    database_url="postgresql+asyncpg://rag:secret@localhost:5432/rag",
    db_connect_timeout_seconds=4,
    db_statement_timeout_ms=12_000,
    db_pool_size=7,
    db_pool_timeout_seconds=9,
)


def test_every_connection_and_statement_has_an_explicit_timeout() -> None:
    args = connect_args(SETTINGS)

    assert args["timeout"] == 4
    assert args["server_settings"]["statement_timeout"] == "12000"


def test_the_server_times_out_a_statement_before_the_client_does() -> None:
    # PostgreSQL then cancels the statement with SQLSTATE 57014, which is reported
    # as a timeout instead of a lost connection.
    assert connect_args(SETTINGS)["command_timeout"] > 12


def test_pooled_engines_also_bound_the_wait_for_a_connection() -> None:
    options = engine_options(SETTINGS)

    assert options["pool_timeout"] == 9
    assert options["pool_size"] == 7
    assert options["pool_pre_ping"] is True
    assert options["connect_args"] == connect_args(SETTINGS)


async def test_engines_are_created_without_connecting() -> None:
    pooled = create_engine(SETTINGS)
    one_shot = create_migration_engine(SETTINGS)

    assert pooled.url.drivername == "postgresql+asyncpg"
    assert type(one_shot.pool).__name__ == "NullPool"
    await pooled.dispose()
    await one_shot.dispose()


class DriverError(Exception):
    """Stands in for the driver error SQLAlchemy wraps, with its SQLSTATE."""

    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"sqlstate {sqlstate}")
        self.sqlstate = sqlstate


def dbapi_error(
    sqlstate: str | None, *, invalidated: bool = False
) -> sa_exc.DBAPIError:
    return sa_exc.DBAPIError(
        "SELECT 1", None, DriverError(sqlstate), connection_invalidated=invalidated
    )


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (ConnectionRefusedError("refused"), StorageUnavailableError),
        (TimeoutError("connect timed out"), StorageUnavailableError),
        (dbapi_error(None, invalidated=True), StorageUnavailableError),
        (dbapi_error("08006"), StorageUnavailableError),
        (dbapi_error("57P01"), StorageUnavailableError),
        (dbapi_error("57P03"), StorageUnavailableError),
        (dbapi_error("53300"), StorageUnavailableError),
        (dbapi_error("40001"), StorageUnavailableError),
        (dbapi_error("40P01"), StorageUnavailableError),
        (dbapi_error("57014"), StorageTimeoutError),
        (sa_exc.TimeoutError("pool exhausted"), StorageTimeoutError),
    ],
)
def test_outages_and_timeouts_become_transient_storage_errors(
    raised: Exception, expected: type[Exception]
) -> None:
    with pytest.raises(expected) as caught, translated_errors():
        raise raised

    assert caught.value.__cause__ is raised


@pytest.mark.parametrize(
    "raised",
    [dbapi_error("42P01"), dbapi_error("23505"), LeaseLostError("taken over")],
)
def test_bugs_and_domain_errors_pass_through_unchanged(raised: Exception) -> None:
    with pytest.raises(type(raised)) as caught, translated_errors():
        raise raised

    assert caught.value is raised
