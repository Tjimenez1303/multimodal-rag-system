from multimodal_rag.adapters.postgres.engine import (
    connect_args,
    create_engine,
    create_migration_engine,
    engine_options,
)
from multimodal_rag.shared.config import DatabaseSettings

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
    assert args["command_timeout"] == 12
    assert args["server_settings"]["statement_timeout"] == "12000"


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
