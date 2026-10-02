# How-to guides

Recipes for the changes made most often. Every change also follows the spec-driven
workflow in [AGENTS.md](../../AGENTS.md), so a new feature starts with a specification
under [`specs`](../../specs). Paths are relative to `backend/src/multimodal_rag/`.

## Add an endpoint

1. Write the behavior as a use case in `ingestion/use_cases/` or
   `answering/use_cases/`. Its constructor takes the ports it needs as keyword
   arguments, and `__call__` returns domain objects or raises domain errors.
2. Unit-test the use case with the fakes in `backend/tests/fakes.py`.
3. Add the request and response bodies to `adapters/http/schemas.py`, with a
   `from_*` class method that maps the domain object to the body.
4. Add the route to the matching `routes_*.py`. Give it an `operation_id`, which becomes
   the function name in the generated frontend client, and list its error statuses with
   `problem_responses(...)`.
5. Expose the use case to the route: add a field to `IngestionState` or
   `AnsweringState` in `adapters/http/dependencies.py`, a `provide_*` function and an
   `Annotated` alias.
6. Build the use case in `bootstrap.py`, in `_ingestion_state` or `_answering_state`.
7. Add the operation to the feature's OpenAPI contract in
   `specs/<feature>/contracts/openapi.yaml`. The contract tests fail until the served
   API and the contract agree.
8. Regenerate the frontend client:

   ```bash
   uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json
   npm --prefix frontend run generate-client
   ```

## Add or replace an external service

To add a capability, such as a new model, or to swap a provider, such as another vector
database:

1. If the core does not already have a port for it, add a `Protocol` to the feature's
   `ports.py`, written in domain terms with no SDK types.
2. Create an adapter under `adapters/<name>/` that implements the protocol.
   - Give every call an explicit timeout from settings.
   - Translate failures: unreachable or timed out into `ProviderUnavailableError` or
     `ProviderTimeoutError`, rejected requests into `ProviderResponseError`.
     `adapters/provider_errors.py` already does this for HTTP.
   - Retry transient failures with `call_with_retry` and `RetryPolicy.for_providers`.
3. Add a fake to `backend/tests/fakes.py`, so use cases can be tested without the
   service. `test_fakes_match_ports.py` checks the fake against the protocol.
4. Test the adapter: with respx for HTTP, or in `tests/integration/` with
   testcontainers for a real service.
5. Add its settings (URL, model, timeout) to `ProviderSettings`, `ApiSettings` or
   `WorkerSettings`.
6. Build it in `bootstrap.py` and pass it to the use cases. Nothing under `ingestion/` or
   `answering/` changes when a provider is swapped.

## Change the database schema

1. Edit `adapters/postgres/tables.py`. Follow the naming convention already declared on
   `metadata`, and use a `CHECK` built with `_one_of` for enumerations.
2. Generate a migration and read it before keeping it:

   ```bash
   uv run --directory backend alembic revision --autogenerate -m "<change>"
   ```

   Autogenerate misses some things, such as triggers, partial index predicates and data
   changes. Add those by hand, and write a `downgrade` that reverses the upgrade.
3. Update the repository in `adapters/postgres/` and the domain object it maps to.
4. Run the integration tests. `test_migrations_produce_exactly_the_declared_schema`
   fails if the migrations and `tables.py` disagree.
5. Regenerate `docs/backend/schema.sql` so the documentation stays current:

   ```bash
   DATABASE_URL='postgresql+asyncpg://u:p@localhost/db' uv run --directory backend alembic upgrade head --sql
   ```

   Then update the Database page of the architecture drawing.

## Add a setting

1. Add the field to the settings class of the process that reads it in
   `shared/config.py`. A required setting has no default. Document it in the class
   docstring's `Attributes`.
2. If it must fit with another limit, add the check to that class's model validator.
3. Pass it to the adapter or use case in `bootstrap.py`. Use cases never read settings
   themselves.
4. If deployments are expected to change it, add it to the service's environment in
   `compose.yaml` and describe it in `.env.example`.

## Add an error

1. Subclass the right family from `shared/errors.py` in the feature's `errors.py`, for
   example `NotFoundError` for a missing resource or `ConcurrencyError` for a conflict.
2. Give it a `code` in snake case. Clients and the frontend's failure messages rely on
   it, so never rename a published code.
3. Raise it from the domain or the use case. The HTTP status follows from its family
   through `_STATUS_BY_ERROR` in `adapters/http/problems.py`, so only a new family needs
   a new entry there.
4. If the client shows a specific message for it, add the code to
   `frontend/src/failures/messages.ts`.

## Change a model

The models are declared in the `models:` section of `compose.yaml` and injected into the
services as `*_URL` and `*_MODEL` variables.

- To swap the answer or vision model, change `models.vlm.model`. Any model served in the
  OpenAI chat format works, as long as it supports JSON schema responses.
- To swap the embedding model, change `models.embedder.model`, `EMBEDDER_DIMENSIONS`, the
  tokenizer in `backend/embedder_tokenizer.txt` and, if needed, the query instruction.
  Existing vectors are not comparable with the new model, so every document must be
  ingested again into a new collection (`QDRANT_COLLECTION`).
- The reranker adapter is written for the Qwen3 reranker's yes or no prompt. Another
  reranker needs a new `RelevanceJudge` adapter.

## Tune retrieval and answering

| Setting | Effect |
| --- | --- |
| `MAX_UNIT_TOKENS` | Size of a retrieval unit. Needs a re-ingestion |
| `RERANK_CANDIDATES` | Passages the reranker judges |
| `RETRIEVAL_TOP_K` | Passages the answer model receives |
| `MIN_RELEVANCE` | How sure the reranker must be before the model is asked at all |
| `ANSWER_DEADLINE_SECONDS` | Time limit of a whole question |

Measure a change against the labeled questions before keeping it:

```bash
uv run --directory backend python -m tests.evaluation.evaluate_relevance
```
