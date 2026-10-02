# Where to put what

Find the row that matches what you are adding. Paths are relative to
`backend/src/multimodal_rag/` unless they start with `backend/`.

| I want to add | It goes in | Notes |
| --- | --- | --- |
| A business rule about documents, jobs or elements | `ingestion/domain.py` | Entities validate themselves in `__post_init__`. No framework imports |
| A pure ingestion rule, such as a new chunking or linking rule | A module in `ingestion/` next to `retrieval_units.py` | A plain function over domain objects, unit-tested without fakes |
| A rule about questions or answers | A module in `answering/` | Same as above |
| Something the core needs from the outside world | A `Protocol` in `ingestion/ports.py` or `answering/ports.py` | The core owns the interface, the adapter implements it |
| A new operation exposed to clients | A use case class in `ingestion/use_cases/` or `answering/use_cases/` | Constructor takes ports as keyword arguments, `__call__` does the work |
| An HTTP endpoint | `adapters/http/routes_*.py`, bodies in `adapters/http/schemas.py` | Routes only translate HTTP. Logic stays in the use case |
| A use case available to routes | `IngestionState` or `AnsweringState` in `adapters/http/dependencies.py`, plus a provider and an `Annotated` alias | Built in `bootstrap.py` |
| An integration with a service, model or library | A new folder under `adapters/` | Wrap failures in `ProviderError` or `StorageError`, and retry through `shared/resilience.py` |
| A new error | The feature's `errors.py`, subclassing the right family from `shared/errors.py` | Give it a stable `code`. Map its family in `adapters/http/problems.py` only if it needs a new status |
| A setting | The settings class of the process that reads it, in `shared/config.py` | Required settings have no default. Document it in `.env.example` |
| Wiring of a new adapter or use case | `bootstrap.py` | The only place that builds concrete classes |
| A table or column | `adapters/postgres/tables.py`, then a migration in `backend/migrations/versions/` | See [How-to guides](how-to.md#change-the-database-schema) |
| A query | The repository in `adapters/postgres/` that owns the table | Translate driver errors with `transaction` or `connect` from `engine.py` |
| A field stored with each searchable unit | `RetrievalUnit` in `ingestion/domain.py` and `UnitPayload` in `adapters/qdrant/index.py` | Existing points need a re-ingestion to get it |
| A prompt change | `answering/prompting.py` for answers, `adapters/openai_compatible/describer.py` for figures, `reranker.py` for judging | Prompts of the core stay model-independent |
| A Python dependency | `backend/pyproject.toml`, then `uv lock` | Check first that the standard library or an installed dependency does not already do it |
| A test fake for a new port | `backend/tests/fakes.py` | `test_fakes_match_ports.py` checks it matches the port |
| A test | `backend/tests/unit/<layer>/`, `contract/` or `integration/` | See [Testing](testing.md) |

## What never goes where

- Nothing under `ingestion/` or `answering/` imports FastAPI, SQLAlchemy, httpx, Qdrant,
  Docling, pydantic-settings or structlog. import-linter fails the build if it does.
- Routes never search, prompt or extract. They call one use case.
- PDF processing never runs in the API process.
- Use cases never build adapters. They receive them.
