---

description: "Task list for asynchronous PDF ingestion"
---

# Tasks: Asynchronous PDF Ingestion

**Input**: Design documents from `specs/001-async-pdf-ingestion/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/openapi.yaml](contracts/openapi.yaml),
[quickstart.md](quickstart.md)

**Tests**: Test tasks are REQUIRED for every user story (constitution Principle VIII).

- Unit tests use the fakes in `backend/tests/fakes.py`, which implement the ports, and
  `respx` for HTTP adapters. Never use `MagicMock` or `Mock`.
- Backend coverage MUST stay at or above 90%.
- Write each story's tests first and confirm they fail before implementing.

**Organization**: Phase 1 ships in its own pull request, `chore/scaffold-backend-tooling`,
as decided in the plan. Phases 2 onward ship in `feature/async-pdf-ingestion`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story from spec.md (US1 to US4)
- All paths are relative to the repository root

## Path Conventions

- Package: `backend/src/multimodal_rag/`
- Tests: `backend/tests/` (unit, integration, contract, fixtures)
- Compose files and `.env.example` live at the repository root

---

## Phase 1: Setup (pull request `chore/scaffold-backend-tooling`)

**Purpose**: Repository tooling that every later task relies on. There is no application
code yet beyond a package skeleton and one smoke test.

- [x] T001 Create `backend/.python-version` with the latest Python 3.14 patch available to uv (3.14.7 on 2026-09-28), and `backend/pyproject.toml`:
  - Project `multimodal-rag`, `requires-python = "==3.14.*"`, src layout with package `multimodal_rag`.
  - Dependency group `dev` with pytest, pytest-asyncio, pytest-cov, respx, ruff, mypy, import-linter and pre-commit.
  - No runtime dependencies yet.
- [x] T002 Create the package skeleton with Google-style module docstrings:
  - `backend/src/multimodal_rag/__init__.py`
  - empty `shared/`, `ingestion/` and `adapters/` subpackages, each with an `__init__.py`
- [x] T003 Configure ruff in `backend/pyproject.toml`:
  - Line length 88, target py314.
  - `select = ["E", "W", "F", "I", "B", "C4", "UP", "T20", "G", "ASYNC", "TID251", "D"]`.
  - `[tool.ruff.lint.pydocstyle] convention = "google"`, with `D` ignored under `tests/` so the constitution's Google-style docstrings are enforced.
  - `[tool.ruff.lint.flake8-tidy-imports.banned-api]` bans `unittest.mock.MagicMock` and `unittest.mock.Mock`, with the message "use a fake that implements the port".
  - The ruff formatter is enabled.
- [x] T004 [P] Configure mypy in `backend/pyproject.toml`: `strict = true`, `plugins = ["pydantic.mypy"]`, `files = ["src", "tests"]`, and pydantic-mypy strict init flags.
- [x] T005 [P] Configure pytest and coverage in `backend/pyproject.toml`:
  - `asyncio_mode = "auto"`, `testpaths = ["tests"]`, and markers `integration` and `slow`.
  - `[tool.coverage.run] source = ["multimodal_rag"]`, `branch = true`.
  - `[tool.coverage.report] fail_under = 90`, `show_missing = true`.
- [x] T006 [P] Add import-linter contracts in `backend/pyproject.toml` under `[tool.importlinter]`:
  - A `forbidden` contract stops `multimodal_rag.ingestion` from importing `multimodal_rag.adapters`, `multimodal_rag.bootstrap`, fastapi, starlette, sqlalchemy, asyncpg, alembic, docling, docling_core, pypdfium2, httpx, qdrant_client, pydantic_settings, structlog, stamina and tokenizers.
  - A `layers` contract orders `multimodal_rag.bootstrap` above `multimodal_rag.adapters`, above `multimodal_rag.ingestion`, above `multimodal_rag.shared`.
- [x] T007 [P] Add a smoke test so the coverage gate runs from day one: `backend/tests/unit/test_package.py` asserts that the package exposes `__version__`.
- [x] T008 [P] Create `.pre-commit-config.yaml` at the repository root with these hooks, mirroring CI:
  - ruff check and ruff format from `astral-sh/ruff-pre-commit`
  - local hooks that run `uv run mypy` and `uv run lint-imports` in `backend/`
  - `crate-ci/typos`
  - `pre-commit-hooks`: detect-private-key, end-of-file-fixer, trailing-whitespace and check-yaml
- [x] T009 [P] Create `_typos.toml` at the repository root that excludes `docs/samples/`, `uv.lock` and the Spanish sample text, and allows the domain terms that typos flags.
- [x] T010 Create `.github/workflows/ci.yml` with a single job running `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy`, `lint-imports` and `pytest --cov`.
  - Pin `actions/checkout` and `astral-sh/setup-uv` by full commit SHA, resolved with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` at implementation time.
  - Set `permissions: contents: read` and `persist-credentials: false`.
- [x] T011 [P] Create `.github/workflows/zizmor.yml`, which runs zizmor on `.github/workflows/`. Pin the action by full commit SHA with read-only permissions.
- [x] T012 [P] Create `backend/Dockerfile` following the official uv multi-stage pattern:
  - `COPY --from=ghcr.io/astral-sh/uv:<pinned> /uv /uvx /bin/`
  - `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PYTHON_DOWNLOADS=0`
  - cache mounts, `uv sync --locked --no-install-project`, then `uv sync --locked`
  - a runtime stage on `python:3.14-slim-trixie` with non-root user `nonroot` (uid 999)
- [x] T013 Run `uv lock` in `backend/` and commit `backend/uv.lock`. Run `pre-commit run --all-files` and CI locally, and paste the output as evidence in the pull request body.
- [x] T014 Update `AGENTS.md` with the real commands: install (`uv sync`), lint, types, import contracts, tests with coverage, and pre-commit.

**Checkpoint**: The tooling pull request is merged, and `feature/async-pdf-ingestion` is updated from `main`.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: Cross-cutting infrastructure and the domain vocabulary that every story uses.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T015 Add the runtime dependencies to `backend/pyproject.toml`:
  - fastapi, python-multipart, pydantic-settings
  - sqlalchemy[asyncio] 2.1, asyncpg, alembic
  - docling 2.130 and an explicit onnxruntime
  - pypdfium2, httpx, qdrant-client 1.19, structlog 26, stamina 26, tokenizers
  - torch and torchvision from the `pytorch-cpu` index with the `sys_platform == 'linux'` marker (research §1, §6)

  Add reportlab and pypdf to the `dev` group for fixture generation. Refresh `backend/uv.lock`.
- [x] T016 [P] Implement the error hierarchy in `backend/src/multimodal_rag/shared/errors.py`:
  - Root `MultimodalRagError`.
  - Families `ConfigurationError`, `ValidationError`, `NotFoundError`, `ExtractionError`, `ProviderError`, `StorageError`, `ConcurrencyError` and `DataInconsistencyError`.
  - Every error has a stable `code` attribute.
  - Unit tests in `backend/tests/unit/shared/test_errors.py`.
- [x] T017 [P] Implement `Settings` with pydantic-settings in `backend/src/multimodal_rag/shared/config.py`.
  - Required, with no default: `DATABASE_URL`, `QDRANT_URL`, `BLOB_ROOT`, `VLM_URL`, `VLM_MODEL`, `EMBEDDER_URL`, `EMBEDDER_MODEL`.
  - With documented defaults:
    - upload limits: 200 MB and 500 pages
    - `MAX_ATTEMPTS=3`, `LEASE_SECONDS=90`, `HEARTBEAT_SECONDS=30`, `POLL_SECONDS=2`
    - timeouts and retry budgets per provider
    - `FIGURE_DESCRIPTION_ENABLED=true`, `FIGURE_CONCURRENCY=2`, `MAX_UNIT_TOKENS=480`, `EXTRACTION_PAGE_BATCH=4`, `WORKER_MAX_JOBS=20`
    - external call timeouts: `DB_CONNECT_TIMEOUT_SECONDS=5`, `DB_STATEMENT_TIMEOUT_MS=15000`, `QDRANT_TIMEOUT_SECONDS=10`
    - figure rules: `DECORATIVE_MIN_PAGES=3`, `DECORATIVE_MIN_PAGE_SHARE=0.2`, `NEAR_TEXT_MAX_POINTS=72`
    - `LOG_FORMAT` (`json` or `console`)
  - A missing required value raises `ConfigurationError` at startup with the variable name.
  - Unit tests in `backend/tests/unit/shared/test_config.py`.
- [x] T018 [P] Implement structured logging in `backend/src/multimodal_rag/shared/logging.py`:
  - structlog over stdlib, with `ProcessorFormatter` using `foreign_pre_chain`, `PositionalArgumentsFormatter`, `merge_contextvars` and ISO timestamps.
  - JSON renderer when `LOG_FORMAT=json`, console renderer otherwise.
  - `bind_correlation(request_id=..., job_id=...)` helpers using contextvars.
  - Unit tests in `backend/tests/unit/shared/test_logging.py` assert that the JSON output has `request_id` and `job_id` and that `%s` arguments are rendered.
- [x] T019 [P] Implement retry policies in `backend/src/multimodal_rag/shared/resilience.py`:
  - stamina with exponential backoff and jitter, retrying only transient `ProviderError` subclasses (`ProviderUnavailableError`, `ProviderTimeoutError`), with attempts and timeouts from `Settings`.
  - Unit tests in `backend/tests/unit/shared/test_resilience.py` use `stamina.set_testing`.
- [x] T020 Implement the domain value objects and enums in `backend/src/multimodal_rag/ingestion/domain.py`, with no framework imports:
  - `JobStatus`: `pending`, `processing`, `completed`, `failed`
  - `JobStage`: `extracting`, `describing_figures`, `building_units`, `embedding`, `indexing`, `finalizing`
  - `FailureCode`: `encrypted_document`, `corrupt_document`, `no_extractable_text`, `provider_unavailable`, `interrupted_repeatedly`, `internal_error`
  - `ElementKind`: `heading`, `paragraph`, `list_item`, `caption`, `table`, `image`, `page_furniture`
  - `TextOrigin`: `text_layer`, `recognized`
  - `DescriptionStatus`: `described`, `skipped`, `not_described`
  - `RelationshipKind`: `caption_of`, `title_of`, `describes`, `near`, `continues`
  - `BoundingBox`, as a frozen dataclass in PDF points with `origin = top_left`. It validates "`left < right`, `top < bottom`, and every value within the page size" (data-model.md).
- [x] T021 Add the domain entities to `backend/src/multimodal_rag/ingestion/domain.py`:
  - `Document`, whose `sha256` is "64 hex chars" and whose `file_name` is the "Original name as uploaded, at most 255 characters".
  - `IngestionJob`, with forward-only transition methods (`start`, `advance`, `complete`, `fail`) that raise `ConcurrencyError` on an invalid transition.
  - `JobSummary`, `ExtractedElement` (requires `page` and `bbox`), `ElementRelationship` and `RetrievalUnit`.
- [x] T022 [P] Add unit tests for the domain in `backend/tests/unit/ingestion/test_domain.py`:
  - bounding box validation
  - forward-only job transitions, including the rejected `completed → processing`
  - a missing page or box on an element raises `DataInconsistencyError`
- [x] T023 Define the ports as `typing.Protocol` in `backend/src/multimodal_rag/ingestion/ports.py`, each with Google-style docstrings:
  - `DocumentRepository`, `JobQueue`, `ElementRepository`, `BlobStorage`
  - `PdfInspector`, `DocumentExtractor`, `FigureDescriber`, `Embedder`
  - `TokenCounter`, `VectorIndex` (`ensure_collection`, `upsert_units`, `publish`, `delete_document`, `search_hybrid(query_text, query_vector, limit, document_ids=None)`), `Clock`
- [x] T024 [P] Implement one in-memory fake per port in `backend/tests/fakes.py`:
  - `InMemoryDocumentRepository`, `InMemoryJobQueue` (with lease and fencing semantics), `InMemoryElementRepository`, `InMemoryBlobStorage`
  - `FakePdfInspector`, `FakeExtractor` (canned elements), `FakeFigureDescriber` (can be set to fail), `FakeEmbedder` (deterministic 1024-dim vectors from a hash)
  - `WordTokenCounter`, `InMemoryVectorIndex` (its `search_hybrid` scores simple word overlap and honors `visible`), `FrozenClock`
- [x] T025 [P] Implement the filesystem `BlobStorage` in `backend/src/multimodal_rag/adapters/storage/filesystem.py`:
  - Content-addressed keys, `documents/{sha256}.pdf` and `figures/{document_id}/{element_id}.png`.
  - Writes go to a temporary file followed by an atomic rename.
  - Unit tests in `backend/tests/unit/adapters/test_filesystem_storage.py` use `tmp_path`.
- [x] T026 Create the async engine factories (pooled for the API and the worker, `NullPool` for migrations) and the database readiness probe in `backend/src/multimodal_rag/adapters/postgres/engine.py`. Repositories use SQLAlchemy Core, so no ORM session factory is needed, and the SQLAlchemy table metadata in `backend/src/multimodal_rag/adapters/postgres/tables.py`:
  - `documents`, with `UNIQUE(sha256)`.
  - `ingestion_jobs`, with an index on `(status, lease_expires_at)`.
  - `extracted_elements` and `element_relationships`.
  - Columns exactly as in data-model.md.
  - The engine sets `connect_args` with `timeout=DB_CONNECT_TIMEOUT_SECONDS` and `server_settings={"statement_timeout": DB_STATEMENT_TIMEOUT_MS}`, and the pool sets `pool_timeout` (constitution Principle VI).
- [x] T027 Initialize Alembic:
  - `backend/alembic.ini` and `backend/migrations/env.py` (async).
  - The first revision `backend/migrations/versions/0001_initial_schema.py` creates the tables from T026, plus a `NOTIFY ingestion_jobs` trigger on insert.
- [x] T028 [P] Create the test fixture generator `backend/tests/fixtures/build_fixtures.py` (reportlab plus pypdf). It writes these files to `backend/tests/fixtures/`, each at most 3 pages:
  - `digital.pdf`: heading, paragraphs, a table and a labeled diagram with a caption
  - `split_table.pdf`: a table that continues on page 2 with a repeated header
  - `scanned.pdf`: image-only pages
  - `encrypted.pdf`: password protected
  - `not_a_pdf.pdf`: plain text with a `.pdf` name

  Commit the generated fixtures.
- [x] T029 Implement the FastAPI application factory in `backend/src/multimodal_rag/adapters/http/app.py`:
  - request id middleware that reads `X-Request-ID` or generates one, binds it for logging and echoes it
  - RFC 9457 problem details in `backend/src/multimodal_rag/adapters/http/problems.py`, mapping every `MultimodalRagError` family to a status and `code` in one place
  - `/health/live` and `/health/ready` (database and blob storage)
- [x] T030 Implement the composition root `backend/src/multimodal_rag/bootstrap.py`. It builds settings, logging, adapters and use cases for two entry points, `api` and `worker`, and it is the only module that imports both `ingestion` and `adapters`. In this phase the worker entry point only starts, logs readiness and idles. User story tasks register their adapters here.
- [x] T031 Create `compose.yaml` at the repository root:
  - Services: `postgres` (18, healthcheck), `qdrant` (1.19, healthcheck), `migrate` (one-shot `alembic upgrade head`), `api` (published on 127.0.0.1:8000) and `worker`.
  - A named volume for blobs.
  - A `models` top-level element with `vlm: ai/qwen3.5:9b`, whose runtime flags disable thinking with `--chat-template-kwargs {"enable_thinking": false}`.
  - `embedder: ai/qwen3-embedding:0.6b`, with runtime flags `--embeddings --ubatch-size 2048 --batch-size 2048` (research §11, §13).
  - Long syntax with `endpoint_var: VLM_URL`, `model_var: VLM_MODEL`, `endpoint_var: EMBEDDER_URL` and `model_var: EMBEDDER_MODEL`.
- [x] T032 [P] Create `.env.example` at the repository root. Document every variable from T017 with its default or "required". Also document the one-time `docker desktop enable model-runner --tcp 12434 --cors none` prerequisite.
- [x] T033 [P] Add an integration test fixture module `backend/tests/integration/conftest.py` that starts PostgreSQL 18 and Qdrant 1.19 with testcontainers and applies the Alembic migrations. Mark the tests `integration`.

**Checkpoint**: `docker compose up` starts healthy `postgres`, `qdrant`, `api` and an idle `worker`. `uv run pytest` passes with coverage at or above 90%. `lint-imports` passes.

---

## Phase 3: User Story 1 - Upload a manual and follow its processing (Priority: P1) 🎯 MVP

**Goal**: An upload returns a tracking identifier immediately. The worker processes the document in the background, and the job can be followed through pending, processing, completed or failed with progress and a reason.

**Independent Test**: Upload `docs/samples/faa-powerplant-ch4-ignition-electrical.pdf`, get 202 in under 2 seconds, and poll until completed. Upload `backend/tests/fixtures/not_a_pdf.pdf` and get 415 without a job (quickstart scenarios 1 and 4).

### Tests for User Story 1 (REQUIRED) ⚠️

> Write these tests first and confirm they fail before implementation.

- [x] T034 [P] [US1] Unit tests for `SubmitDocument` in `backend/tests/unit/ingestion/test_submit_document.py`, using the fakes:
  - A new file creates a document and a pending job.
  - Identical content that already completed returns the existing ids with `already_ingested=true`.
  - Identical content still pending or processing returns the existing ids with `already_ingested=false`, and a job enqueued concurrently for the same document is reused.
  - Identical content whose last job failed creates a new job.
  - Rejections for a non-PDF, for more than 200 MB and for more than 500 pages create no job.
- [x] T035 [P] [US1] Unit tests for `GetJob` and for the job progress update in `backend/tests/unit/ingestion/test_get_job.py`, covering unknown ids (`JobNotFoundError`) and stage and page progress.
- [x] T036 [P] [US1] Unit tests for `ProcessJob`, stages 1 to 2, in `backend/tests/unit/ingestion/test_process_job_extraction.py`:
  - Extraction progress is reported per page batch, and elements are persisted with page and box.
  - Encrypted, corrupt and no-text documents end `failed` with the matching `FailureCode` and no retry.
  - A write with a stale lease token aborts.
- [x] T037 [P] [US1] Contract tests in `backend/tests/contract/test_upload_and_job_contract.py`. They validate `POST /api/v1/documents` (202, 200 and every error) and `GET /api/v1/jobs/{job_id}` against `specs/001-async-pdf-ingestion/contracts/openapi.yaml`:
  - The FastAPI test client runs the app from `create_app` with the ingestion router, and the use case providers are replaced by fakes through `app.dependency_overrides`.
  - Response bodies are validated with `jsonschema` (`Draft202012Validator` and a `referencing` registry over the contract), declared in the `dev` group with `pyyaml`.
  - A body declared larger than the limit is answered 413 before the endpoint runs.
- [x] T038 [P] [US1] Integration tests for the Postgres adapters in `backend/tests/integration/test_postgres_documents_and_jobs.py`:
  - 10 concurrent registrations of the same sha256 yield one document (`ON CONFLICT`).
  - A claim uses `FOR UPDATE SKIP LOCKED`, so two concurrent claimers never get the same job.
  - A write guarded by an old lease token affects zero rows.
  - Two concurrent enqueues for the same document keep one job that has not failed, and a failed job does not block a new one.
- [x] T039 [P] [US1] Integration test for the Docling extractor and the pypdfium2 inspector in `backend/tests/integration/test_docling_extractor.py`, marked `slow`:
  - On `digital.pdf`, it yields headings, paragraphs, a table and an image with its PNG crop, each with page and a top-left box.
  - On `scanned.pdf`, it yields recognized text with a confidence, and reports the page as recognized.
  - `encrypted.pdf` raises `EncryptedDocumentError`, and a truncated PDF raises `CorruptDocumentError`.
  - The inspector reports the page count, detects `encrypted.pdf`, and rejects `not_a_pdf.pdf` by content.
  - `digital.pdf` converted with a page batch of 1 yields the same reading order and heading levels as a batch of 3.

### Implementation for User Story 1

- [x] T040 [P] [US1] Implement the `PdfInspector` adapter in `backend/src/multimodal_rag/adapters/docling/pdfium.py` with pypdfium2. It validates by content, returns the page count and flags encrypted files, without rendering.
- [x] T041 [P] [US1] Implement the Postgres `DocumentRepository` in `backend/src/multimodal_rag/adapters/postgres/documents.py`, with `register` via `INSERT … ON CONFLICT (sha256) DO NOTHING RETURNING id` falling back to a select, plus `get`. `list_page` arrives with T075.
- [x] T042 [US1] Implement the Postgres `JobQueue` in `backend/src/multimodal_rag/adapters/postgres/job_queue.py`:
  - Migration `backend/migrations/versions/0002_one_active_job_per_document.py` adds the partial unique index `ingestion_jobs(document_id) WHERE status <> 'failed'` (PostgreSQL docs, "Partial Indexes", example 11.3).
  - `enqueue` returns the stored job, using `INSERT … ON CONFLICT (document_id) WHERE status <> 'failed' DO NOTHING` with the predicate rendered as a literal, and falling back to the existing job.
  - `claim(worker_id)` with `SELECT … FOR UPDATE SKIP LOCKED` over pending jobs. It sets `processing`, increments `attempt` and issues `lease_token` and `lease_expires_at`.
  - `heartbeat`, `update_progress`, `complete` and `fail`, each conditioned on `lease_token`.
  - `get` and `latest_for_document`.
  - Reclaiming expired leases is T070.
- [x] T043 [P] [US1] Implement the Postgres `ElementRepository` in `backend/src/multimodal_rag/adapters/postgres/elements.py`. `replace_for_document(document_id, elements, relationships, lease_token)` runs in one transaction guarded by the lease token.
- [x] T044 [US1] Implement the Docling `DocumentExtractor` in `backend/src/multimodal_rag/adapters/docling/extractor.py`:
  - One `DocumentConverter` per worker process, warmed at startup, with RapidOCR on onnxruntime, TableFormer, the picture classifier, and `generate_picture_images` with `images_scale=2.0`.
  - Artifacts from `DOCLING_ARTIFACTS_PATH`. Threads from `EXTRACTION_THREADS` for both `AcceleratorOptions.num_threads` and the docling-parse `parser_threads`.
  - Converts in page batches of `EXTRACTION_PAGE_BATCH` with `page_range`, as in docling-serve's split processing example, and yields one batch at a time. `reading_order` continues across batches.
  - Heading levels come from document-wide signals read once before the first batch: the PDF outline, then section numbering, then level 1. Docling's heading hierarchy renumbers levels inside each conversion, so it is not used per batch.
  - Maps Docling items to domain `ExtractedElement` in `backend/src/multimodal_rag/adapters/docling/mapping.py`: boxes via `to_top_left_origin(page_height)`, page furniture from the furniture layer, text nested at any depth inside a figure as its labels and inside a table as part of it, and `image_class` from `meta.classification`.
  - Each batch has the conversion timeout Docling recommends (`EXTRACTION_BATCH_TIMEOUT_SECONDS`), and a batch that Docling returns as a partial success fails the job instead of dropping pages.
  - Text elements on pages without a text layer are `recognized`, with the page's `ocr_score` as confidence (Docling's confidence scores API).
  - Returns crops as PNG bytes in `ExtractionBatch.images`. `ProcessJob` stores them.
  - Classifies unreadable files with pypdfium2 before conversion, because Docling reports encrypted and corrupt files with the same error: `EncryptedDocumentError` or `CorruptDocumentError`.
- [x] T045 [US1] Implement the use cases `SubmitDocument` and `GetJob` in `backend/src/multimodal_rag/ingestion/use_cases/intake.py`:
  - `SubmitDocument` hashes and counts the chunks it receives while `BlobStorage` stores them under a staging key, then moves the file to its content-addressed key.
  - It enforces the limits through `PdfInspector` before registration.
  - It returns `already_ingested` per FR-016 and reuses the job of identical content that has not failed.
  - It logs `document uploaded` with `document_id`, `job_id`, `size_bytes`, `page_count` and `already_ingested`. The file name and content are never logged (FR-021).
- [x] T046 [US1] Implement `ProcessJob` stages `extracting` and `finalizing` in `backend/src/multimodal_rag/ingestion/use_cases/processing.py`:
  - Runs the extractor, advancing it one batch at a time with `asyncio.to_thread`.
  - Stores figure crops under `figures/{document_id}/{element_id}.png`.
  - Fails with `no_extractable_text` when no element carries text.
  - Persists elements through `ElementRepository`.
  - Builds `JobSummary`, including `recognized_pages`.
  - Completes or fails the job with `FailureCode`.
  - Logs every transition with `job_id` and never logs document content.
- [x] T047 [US1] Implement the upload and job routes in `backend/src/multimodal_rag/adapters/http/routes_ingestion.py`, with schemas in `backend/src/multimodal_rag/adapters/http/schemas.py`:
  - A pure ASGI middleware in `backend/src/multimodal_rag/adapters/http/body_limit.py` answers 413 problem details with `file_too_large` when `Content-Length` exceeds the upload limit, before the body is read, and counts the bytes of bodies without that header. FastAPI parses the multipart body before any dependency or endpoint runs, so the check cannot live in the route.
  - `POST /api/v1/documents` streams the spooled upload to `SubmitDocument` in 1 MiB chunks and returns 202 while the job is pending or processing, or 200 when identical content already completed, with a `Location` header pointing to the job.
  - `GET /api/v1/jobs/{job_id}`.
  - Routes receive their use cases through `Annotated[..., Depends(...)]` providers that read the lifespan state.
  - Responses match the OpenAPI contract.
- [x] T048 [US1] Implement the worker loop in `backend/src/multimodal_rag/adapters/worker/loop.py`, started by `bootstrap.run_worker` through `python -m multimodal_rag worker`:
  - Wakes on `LISTEN ingestion_jobs` from a dedicated asyncpg connection with reconnection, in `backend/src/multimodal_rag/adapters/postgres/job_notifications.py`, with a `POLL_SECONDS` fallback, and claims one job at a time.
  - Binds the job's `correlation_id` and `job_id` for logging.
  - Runs `ProcessJob`.
  - On SIGTERM it stops claiming and cancels the running attempt, whose lease then expires.
  - Unit tests in `backend/tests/unit/adapters/test_worker_loop.py`.
- [x] T049 [US1] Bake the Docling models into the single backend image in `backend/Dockerfile`: `docling-tools models download layout tableformer picture_classifier rapidocr --rapidocr-backend-lang onnxruntime:ch -o /opt/docling-models`, owned by the non-root user, with `DOCLING_ARTIFACTS_PATH=/opt/docling-models`. `api`, `worker` and `migrate` keep sharing one image with different commands.

**Checkpoint**: Quickstart scenarios 1 and 4 pass. The job completes with a summary, and the elements are stored.

---

## Phase 4: User Story 2 - Faithful capture of text, tables and images (Priority: P2)

**Goal**: Elements keep page, box and relationships. Figures get labels and a local description. Content becomes structure-aware retrieval units indexed with dense and BM25 vectors, visible only after completion.

**Independent Test**: Ingest the FAA and INSST samples, then inspect `GET /api/v1/documents/{id}/elements`:

- Every element has a page and a box.
- Tables are whole, and figures link to captions and labels.
- `split_table.pdf` shows a `continues` link and one retrieval unit citing both pages.

(Quickstart scenarios 2 and 3.)

### Tests for User Story 2 (REQUIRED) ⚠️

- [x] T050 [P] [US2] Unit tests for the relationship rules in `backend/tests/unit/ingestion/test_relationships.py`:
  - Caption links from the extractor are kept, and a caption the extractor left alone is linked to the nearest image (`caption_of`) or table (`title_of`) in the same column, or across a page break.
  - `near` links the closest paragraph or list item in the same column within `NEAR_TEXT_MAX_POINTS` on the same page, and on the next page when the caption continues there.
  - `continues` for tables "on consecutive pages with the same column count", the earlier part in the lower half of its page and the later part in the upper half, with only page furniture, images or the parts' captions between them (research §8), including negative cases for a different column count and body text in between.
  - Repeated-header detection.
- [x] T051 [P] [US2] Unit tests for the retrieval unit builder in `backend/tests/unit/ingestion/test_retrieval_units.py`:
  - Breaks at headings, tables and figures.
  - Merges paragraphs under the same headings up to `MAX_UNIT_TOKENS`, measured on the contextualized text (heading path and text).
  - Splits oversize paragraphs only at sentence ends, keeps an oversize sentence whole, and never cuts a table.
  - One unit per table chain citing every page, without the repeated header, and one figure unit from caption plus labels plus description. Decorative images and page furniture yield no content.
  - The heading path follows heading levels, including skipped levels.
  - Units carry `heading_path`, `pages`, `element_ids`, `boxes` and `figure_ids`.
  - Deterministic unit ids.
- [x] T052 [P] [US2] Unit tests for figure handling in `backend/tests/unit/ingestion/test_figures.py`:
  - Marks as decorative and skips `logo`, `icon`, `signature`, `stamp`, `bar_code`, `qr_code`, `full_page_image` and `page_thumbnail`, and images repeated "on at least 3 pages or on at least 20% of the pages" (`is_decorative`).
  - Skips figures below 5% of their page area without marking them decorative.
  - Identifier verification flags tokens mixing letters and digits that are absent from labels and caption (FR-028).
  - The description context holds the caption and the nearby text.
- [x] T053 [P] [US2] Unit tests for `ProcessJob` stages `describing_figures` to `indexing` in `backend/tests/unit/ingestion/test_process_job_enrichment.py`:
  - Descriptions run with concurrency 2.
  - A `FakeFigureDescriber` failure marks `not_described` and the job still completes (FR-027). Once the model is unreachable, the remaining figures are not sent to it.
  - With descriptions disabled every figure is `skipped`.
  - The summary counts described, skipped and not described figures, table chains and retrieval units.
  - Units are upserted with `visible=false`, then published on completion.
  - On failure, points are deleted by `document_id` (FR-018).
  - Re-processing yields the same point ids (FR-015).
  - Attempt 2 leaves no point that only attempt 1 wrote, because each attempt starts by deleting the document's points.
  - When the embedder exhausts its retries, `failure_reason` names the service and contains no document content.
  - The embedding input is truncated to `EMBEDDER_MAX_INPUT_TOKENS`.
- [x] T054 [P] [US2] respx tests for the OpenAI-compatible adapters in `backend/tests/unit/adapters/test_openai_compatible.py`:
  - The describer sends the base64 `image_url` data URI, the caption and the neighboring text, `chat_template_kwargs.enable_thinking=false`, and the instruction to answer in the language of the caption and surrounding text, or in English when there is none. Images larger than 1280 px are downscaled.
  - Maps timeouts, connection errors, 429 and 5xx to transient errors, and other 4xx and malformed answers to non-retryable errors.
  - The embedder batches inputs by `EMBEDDER_BATCH_SIZE`, keeps the input order and validates 1024 dimensions, raising `DataInconsistencyError` otherwise.
  - Unit tests for the `TokenCounter` adapter in `backend/tests/unit/adapters/test_huggingface_tokenizer.py` with a tokenizer built in the test, plus a check of the baked Qwen3-Embedding tokenizer.
- [x] T055 [P] [US2] Integration test for the Qdrant `VectorIndex` in `backend/tests/integration/test_qdrant_index.py`:
  - The collection has dense (1024, cosine) and `bm25` sparse (IDF) vectors, plus payload indexes.
  - Upserts are idempotent.
  - `publish` flips `visible`, and `delete_document` removes all points.
  - `search_hybrid` returns a figure unit in the top 5 for one of its labels and never returns points with `visible=false`.
  - An unreachable Qdrant URL raises `ProviderUnavailableError` after the retry budget.
- [x] T056 [P] [US2] Contract tests for `GET /api/v1/documents/{document_id}/elements` (200, 400, 404, and 409 before completion) and `GET /api/v1/documents/{document_id}/images/{element_id}` in `backend/tests/contract/test_elements_contract.py`.

### Implementation for User Story 2

- [x] T057 [P] [US2] Implement the relationship rules in `backend/src/multimodal_rag/ingestion/relationships.py`: the caption fallback, proximity, and table continuation with repeated-header detection (research §8, §9). The Docling adapter emits `caption_of` and `title_of` from Docling's `captions` references, marks those texts as captions, and reports page sizes in `ExtractionBatch`.
- [x] T058 [P] [US2] Implement the figure policy in `backend/src/multimodal_rag/ingestion/figures.py`:
  - The relevance filter: classes, the 5% area threshold, and images repeated on at least `DECORATIVE_MIN_PAGES` pages or `DECORATIVE_MIN_PAGE_SHARE` of the pages, compared by image content hash.
  - The identifier verifier.
  - The neighbor-context selector that feeds the description prompt.
- [x] T059 [US2] Implement the retrieval unit builder in `backend/src/multimodal_rag/ingestion/retrieval_units.py` using the `TokenCounter` port, with unit keys stable across runs (research §7).
- [x] T060 [P] [US2] Implement the `TokenCounter` adapter (`count` and `truncate`) in `backend/src/multimodal_rag/adapters/tokenizer/huggingface.py`, loading the Qwen3-Embedding `tokenizer.json` from `EMBEDDER_TOKENIZER_PATH`.
- [x] T061 [P] [US2] Implement the OpenAI-compatible `FigureDescriber` and `Embedder` in `backend/src/multimodal_rag/adapters/openai_compatible/`:
  - httpx with timeouts and the provider retry policy.
  - Images downscaled to at most 1280 px on the long side.
  - The prompt asks for a short description in the language of the caption and surrounding text (English when there is none) plus every printed label verbatim (FR-026).
- [x] T062 [P] [US2] Implement the Qdrant `VectorIndex` in `backend/src/multimodal_rag/adapters/qdrant/index.py`:
  - `ensure_collection`, which creates the payload indexes before inserts.
  - `upsert_units`, using `uuid5` point ids and server-side `Document(model="qdrant/bm25")` with the language-neutral options of research §12.
  - `publish`, `delete_document`, and `search_hybrid`, which runs `prefetch` on `dense` and `bm25` with RRF fusion and filters `visible=true`.
  - The client uses `timeout=QDRANT_TIMEOUT_SECONDS`, and every call is wrapped in the provider retry policy for connection errors, timeouts and 5xx.
- [x] T063 [US2] Extend `ProcessJob` in `backend/src/multimodal_rag/ingestion/use_cases/processing.py` with the stages `describing_figures`, `building_units`, `embedding` and `indexing`:
  - Each attempt starts with `VectorIndex.delete_document(document_id)` before any upsert.
  - The figure policy and the relationships are computed after extraction.
  - Descriptions are kept on the figures and persisted with the other elements in the single fenced replacement at the end of the attempt, since an interrupted attempt restarts from scratch (FR-025).
  - The summary is updated.
  - Points are published after the elements are stored and before the job completes, and deleted on failure.
  - When a provider exhausts its retry budget, `failure_reason` names the service (`embedding model`, `vector index`) and never includes document content (FR-017).
- [x] T064 [US2] Implement `ListDocumentElements` and `GetElementImage` in `backend/src/multimodal_rag/ingestion/use_cases/library.py`, and their routes in `backend/src/multimodal_rag/adapters/http/routes_documents.py`:
  - Cursor pagination with a page and kind filter, and every relationship that touches each element. Migration `backend/migrations/versions/0004_index_relationships_by_target.py` indexes relationships by target for that lookup.
  - 409 `ingestion_not_completed` when the latest job has not completed.
  - PNG served from `BlobStorage`.
- [x] T065 [US2] Add the Qwen3-Embedding tokenizer download to `backend/Dockerfile` from `backend/embedder_tokenizer.txt` (also cached by CI), with `EMBEDDER_TOKENIZER_PATH`, and wire the adapters in `backend/src/multimodal_rag/bootstrap.py`, calling `ensure_collection` at worker startup.

**Checkpoint**: Quickstart scenarios 2 and 3 pass. SC-004, SC-005 and SC-012 can be checked on the sample set.

---

## Phase 5: User Story 3 - Ingest many manuals without degrading the service (Priority: P2)

**Goal**: A crashed attempt is retried from scratch up to three times while staying `processing`, and never runs on two workers at once. Uploads and status stay fast under a 100-document backlog, and replicas speed up the batch.

**Independent Test**: Quickstart scenario 5 (kill the worker mid-job) and scenario 7 (100 uploads with p95 under 2 s, faster with `--scale worker=2`).

### Tests for User Story 3 (REQUIRED) ⚠️

- [x] T066 [P] [US3] Integration tests for lease recovery in `backend/tests/integration/test_postgres_documents_and_jobs.py` (`TestLeaseRecovery`), next to the other queue tests:
  - An expired lease is reclaimed with `attempt` incremented and a new token, and status stays `processing`.
  - The claim that would exceed `max_attempts` sets `failed` with `interrupted_repeatedly`.
  - A heartbeat keeps a lease alive, and a heartbeat with an old token fails.
- [x] T067 [P] [US3] Unit tests for the worker loop in `backend/tests/unit/adapters/test_worker_loop.py`, using `InMemoryJobQueue` and `FrozenClock`:
  - The heartbeat task renews every `HEARTBEAT_SECONDS`, and a transient renewal failure does not stop the job.
  - A lost lease stops processing.
  - The process exits after `WORKER_MAX_JOBS` so compose restarts it.
- [x] T068 [P] [US3] End-to-end crash test in `backend/tests/integration/test_crash_recovery.py`, marked `slow` (research §16):
  - The worker runs as a subprocess, `python -m tests.integration.worker_process`, which installs the respx routes of `tests/integration/model_apis.py` before calling `bootstrap.run_worker()`, because respx only intercepts requests in its own process.
  - The first worker holds Qdrant's publish request, so its attempt stops after storing units and elements. The test kills it with SIGKILL there, with `LEASE_SECONDS=5` and `HEARTBEAT_SECONDS=1`.
  - A second worker must finish the job on attempt 2. A byte-distinct copy of the same fixture is the clean run: both report the same `retrieval_units`, the crashed document has exactly that many visible points and no hidden ones, and both store the same number of elements. Counts are filtered by document in a Qdrant collection unique to the test.
- [x] T069 [P] [US3] Load script `backend/tests/load/upload_backlog.py`, runnable manually and not part of CI, with unit tests of its pure helpers in `backend/tests/load/test_upload_backlog.py` (research §16):
  - It uploads byte-distinct copies of a sample (a PDF comment with a run id), in a baseline, a concurrent backlog and a probe phase, then checks every job's status in rounds, and prints p50, p95, maximum, timeouts and failures per phase (SC-006).
  - With `--wait` it waits for every job and prints the total processing time, from the first job created to the last finished, for the replica comparison of scenario 7.

### Implementation for User Story 3

- [x] T070 [US3] Extend `claim` in `backend/src/multimodal_rag/adapters/postgres/job_queue.py`:
  - Include `processing` jobs whose `lease_expires_at < now()`.
  - Fail at the attempt limit with `interrupted_repeatedly`.
  - Measure leases on the database clock, shared by every worker, so the claim port takes no caller time.
- [x] T071 [US3] Add the heartbeat task and lease-loss handling to `backend/src/multimodal_rag/adapters/worker/loop.py`, plus process recycling after `WORKER_MAX_JOBS` with `restart: unless-stopped` in `compose.yaml`. The container healthcheck runs `python -m multimodal_rag worker-health`, which reads `LIVENESS_FILE` and `LIVENESS_MAX_AGE_SECONDS`.
- [x] T072 [US3] Ensure the API stays independent of worker load: hash each upload chunk in a thread in `backend/src/multimodal_rag/ingestion/use_cases/intake.py`, while `UploadFile.read` and the blob writes already run in threads, and set the database pool sizes (`DB_POOL_SIZE`) in `backend/src/multimodal_rag/adapters/postgres/engine.py`.

**Checkpoint**: Quickstart scenarios 5 and 7 pass, and FR-025 and SC-006 are demonstrated.

---

## Phase 6: User Story 4 - Browse the document library (Priority: P3)

**Goal**: List documents with name, page count, latest status and date, and open one to see its latest job.

**Independent Test**: Ingest two documents and let one fail, then list them and open one (spec US4).

### Tests for User Story 4 (REQUIRED) ⚠️

- [x] T073 [P] [US4] Unit tests for `ListDocuments` and `GetDocument` in `backend/tests/unit/ingestion/test_library.py`: newest first, cursor pagination, the latest job per document, a document whose job is not enqueued yet, and `DocumentNotFoundError`.
- [x] T074 [P] [US4] Contract tests for `GET /api/v1/documents` and `GET /api/v1/documents/{document_id}` in `backend/tests/contract/test_library_contract.py`, including invalid cursors and limits (400) and unknown documents (404).

### Implementation for User Story 4

- [x] T075 [US4] Implement `ListDocuments` and `GetDocument` in `backend/src/multimodal_rag/ingestion/use_cases/library.py`. The latest job of a page of documents comes from `JobQueue.latest_for_documents`, one `DISTINCT ON` query in `backend/src/multimodal_rag/adapters/postgres/job_queue.py`, next to `latest_for_document`. The documents page reuses the existing keyset query of `PostgresDocumentRepository.list_page`.
- [x] T076 [US4] Add the library routes to `backend/src/multimodal_rag/adapters/http/routes_documents.py`, with an opaque cursor that encodes `(created_at, id)`.

**Checkpoint**: All four stories work independently.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] ~~T077 [P] Create `compose.ollama.yaml`: `ollama` (0.34, model volume, `ollama list` healthcheck), a one-shot `ollama-pull` for both models, and the worker env pointing `VLM_URL` and `EMBEDDER_URL` at `http://ollama:11434/v1`. Document it in `.env.example` (research §13).~~
- [x] T078 [P] Write `docs/adr/0001-postgres-job-queue.md` in business language with a technical annex. The annex covers the Celery with Redis `visibility_timeout` analysis and its sources (research §2).
- [x] T079 [P] Write `docs/adr/0002-document-extraction-with-docling.md`, with the OmniDocBench and license comparison in the annex (research §6).
- [x] T080 [P] Write `docs/adr/0003-local-models-on-docker-model-runner.md`, with the measurements table in the annex (research §10, §11, §13, §15).
- [x] T081 [P] Write `docs/adr/0004-structure-aware-retrieval-units.md`, covering chunking, figure units and table chains (research §7, §8).
- [x] T082 Rewrite `README.md`:
  - A logical architecture diagram (draw.io) of API, worker, Postgres queue, Qdrant, blob volume and Docker Model Runner.
  - Prerequisites, including the DMR enable command.
  - Setup with `docker compose up`, and how to run the tests.
  - A technical decision log that links the ADRs.
  - The sample documents and their licenses. The INSST guide requires "Origen de los datos: INSST".
- [ ] ~~T083 Create the evaluation harness in `backend/tests/evaluation/`. It is not part of CI because the samples are not versioned.~~
  - ~~`annotations.yaml` lists, for each sample in `docs/samples/`, figures with their expected caption and 2 or 3 labels printed inside them.~~
  - ~~`evaluate.py` prints a table with SC-005 (share of annotated captions linked to their figure), SC-009 (OCR word recall on the 10-page rendered Spanish scan against its text layer, as in research §15) and SC-012 (share of annotated labels whose figure appears in the top 5 of `search_hybrid`).~~
- [ ] ~~T084 Run every scenario in `specs/001-async-pdf-ingestion/quickstart.md` against `docs/samples/`, record the timings and the T083 results against SC-001 to SC-012 in the pull request "Test plan" section, and update research.md §15 if any number changes.~~
- [x] T085 Run the full gate (`ruff`, `mypy`, `lint-imports`, `pytest --cov` at or above 90%, `pre-commit run --all-files` and zizmor), then fix root causes instead of suppressing checks.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. It is a separate pull request that must merge first.
- **Foundational (Phase 2)**: Depends on Phase 1 being merged and the feature branch updated. It blocks every story.
- **US1 (Phase 3)**: Depends on Phase 2. This is the MVP.
- **US2 (Phase 4)**: Depends on Phase 2. It extends `ProcessJob` from US1 (T046 before T063).
- **US3 (Phase 5)**: Depends on the US1 queue and worker (T042, T048).
- **US4 (Phase 6)**: Depends on the US1 repositories (T041, T042) and is otherwise independent.
- **Polish (Phase 7)**: Depends on the stories included in the delivery.

### Within Each User Story

- Write the tests first and see them fail.
- Then build in this order: domain rules, adapters, use cases, routes, worker wiring.
- Tasks marked [P] touch different files and can run together.

### Parallel Opportunities

- **Phase 1**: T004 to T009, T011 and T012 run in parallel after T001 to T003.
- **Phase 2**: T016 to T019, T022, T024, T025, T028, T032 and T033 run in parallel once T020, T021 and T023 exist.
- **US1**: the tests T034 to T039 in parallel, then the adapters T040, T041 and T043 in parallel.
- **US2**: the tests T050 to T056 in parallel, then T057, T058 and T060 to T062 in parallel.
- **US3 and US4**: can proceed in parallel after US1.

---

## Parallel Example: User Story 2

```bash
Task: "Unit tests for relationship rules in backend/tests/unit/ingestion/test_relationships.py"
Task: "Unit tests for retrieval unit builder in backend/tests/unit/ingestion/test_retrieval_units.py"
Task: "respx tests for OpenAI-compatible adapters in backend/tests/unit/adapters/test_openai_compatible.py"
Task: "Integration test for Qdrant VectorIndex in backend/tests/integration/test_qdrant_index.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Merge Phase 1, the tooling pull request.
2. Complete Phase 2, the foundational phase.
3. Complete Phase 3 (US1), then stop and run quickstart scenarios 1 and 4.

### Incremental Delivery

1. US1: upload and tracking (MVP)
2. US2: multimodal capture and indexing, the core of the challenge
3. US3: crash recovery and bulk load
4. US4: document library
5. Polish: ADRs and README

---

## Notes

- Every task leaves `ruff`, `mypy`, `lint-imports` and the tests green before moving on.
- Commits follow Conventional Commits with the `ingestion` scope (for example `feat(ingestion): add postgres job queue`).
- Tasks never introduce `MagicMock`, bare `except`, `print` or f-strings in log calls.
- Quote verbatim the data-model constraints named in a task.
