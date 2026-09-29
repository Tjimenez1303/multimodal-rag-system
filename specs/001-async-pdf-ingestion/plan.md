# Implementation Plan: Asynchronous PDF Ingestion

**Branch**: `feature/async-pdf-ingestion` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-async-pdf-ingestion/spec.md`

## Summary

Technicians upload technical PDFs and immediately receive a job identifier. A separate
worker extracts typed elements with page and position, recognizes text on scanned pages,
describes figures with a local vision model, builds structure-aware retrieval units and
indexes them for hybrid search. Job state and progress live in PostgreSQL, which also acts
as the queue.

- **Claiming work.** Workers claim jobs with `FOR UPDATE SKIP LOCKED`.
- **Crash recovery.** A lease renewed by a heartbeat, plus a fencing token, gives prompt
  recovery after a crash, at most three attempts, and never two workers on one job.
- **Extraction.** Docling (MIT) handles layout, tables, OCR (RapidOCR) and figure crops.
- **Models.** `ai/qwen3.5:9b` describes figures and `ai/qwen3-embedding:0.6b` produces
  dense vectors. Both are served by Docker Model Runner on the host GPU and declared in
  the Compose `models` element.
- **Index.** Qdrant stores each unit with a dense vector and a server-side BM25 sparse
  vector.
- **Startup.** After a one-time `docker desktop enable model-runner`, a single
  `docker compose up` starts everything and pulls the models.

Decisions and sources are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.14 (pinned patch in `.python-version`), managed with uv

**Primary Dependencies**:

- FastAPI 0.141 and pydantic-settings
- SQLAlchemy 2.1 (async) with asyncpg, and Alembic
- Docling 2.130 with onnxruntime, RapidOCR, and torch from the CPU index
- pypdfium2 and httpx
- qdrant-client 1.19
- structlog 26 and stamina 26
- Hugging Face `tokenizers`, for the embedding model's tokenizer

**Storage**:

- PostgreSQL 18: documents, jobs (also the queue), elements and relationships
- Qdrant 1.19: retrieval units
- A named Docker volume: PDFs and figure crops

**Testing**:

- pytest, pytest-asyncio and pytest-cov
- respx for HTTP adapters
- testcontainers for PostgreSQL and Qdrant integration tests
- Fakes that implement every port. No `MagicMock`

**Target Platform**: Linux containers (arm64 and amd64) through Docker Compose. The
reference machine is an Apple M4 Pro with Docker Desktop at 12 CPUs and 20 GB. Models run
on the host GPU through Docker Model Runner (llama.cpp with Metal).

**Project Type**: web service (REST API plus background worker). The chat client belongs to
a later feature.

**Performance Goals**:

| Criterion | Target |
|---|---|
| SC-001 | Upload acknowledged in under 2 s |
| SC-002 | Status fresh within 5 s |
| SC-003 | 100 digital pages in under 4 min, excluding descriptions |
| SC-010 | 100 scanned pages in under 10 min |
| SC-011 | Descriptions add at most 8 s per figure on average with the model on the host accelerator (measured 6.0 s on digital pages, about 10 s on scanned pages) |
| SC-006 | p95 upload and status latency under 2 s while 100 documents are queued |

**Constraints**:

- Everything runs locally, with no paid cloud API.
- The domain core imports no framework, SDK or provider.
- Required settings have no default.
- A worker processes one job at a time and scales by replicas.
- Worker memory is budgeted at 6–8 GB, and a worker process recycles after a configurable
  number of jobs to contain Docling's memory growth.

**Scale/Scope**:

- 100 manuals queued at once.
- Documents up to 200 MB and 500 pages.
- One organization, no authentication in this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Hexagonal architecture | `ingestion/` holds the domain, ports and use cases, with no framework imports. `adapters/` holds HTTP, worker, Postgres, Docling, the OpenAI-compatible model API, Qdrant and filesystem code. import-linter `forbidden` and `layers` contracts run in CI | Pass |
| II. Ports and adapters | Ports: `DocumentRepository`, `JobQueue`, `ElementRepository`, `BlobStorage`, `PdfInspector`, `DocumentExtractor`, `FigureDescriber`, `Embedder`, `TokenCounter`, `VectorIndex`, `Clock`. Wiring happens in one composition root driven by settings. Each port has a production adapter and a test fake. Swapping Docker Model Runner for Ollama needs only a different base URL and model names, and another provider needs only a new adapter | Pass |
| III. Asynchronous ingestion | Upload stores, registers, enqueues and returns 202 with `job_id`. The worker runs in a separate process. States are pending, processing, completed and failed, with persisted progress. Workers scale by replicas. Deterministic ids make re-processing idempotent | Pass |
| IV. Multimodal fidelity | Every element has a page and a top-left box in PDF points. Relationships link captions, nearby text and table continuations. Units follow structure, with the token ceiling applied only inside a structural unit | Pass |
| V. Grounded answers | Not in scope for this feature (retrieval and answering come later). This feature provides the prerequisites: page and box on every unit, figure links, BM25 plus dense vectors for hybrid search, and `visible` gating | Pass (prerequisites) |
| VI. Resilience | Every external call has a timeout from settings. stamina retries transient errors with exponential backoff and jitter. There is one root `MultimodalRagError` with families, a specific error per root cause, and `DataInconsistencyError` for internal inconsistencies. ruff rule `E722` forbids bare `except` | Pass |
| VII. Observability | structlog over stdlib renders JSON, with a `logging.getLogger(__name__)` logger per module and lazy `%s` enforced by ruff G. `request_id` travels from the API to the job and the worker, and logs include `job_id`. Document content is never logged | Pass |
| VIII. Test discipline | Unit tests use port fakes and respx, and no `MagicMock` (a ruff banned-api rule enforces it). Integration tests cover the queue semantics against real Postgres. CI fails below 90% coverage. `tasks.md` includes test tasks per story | Pass |
| IX. Configuration and delivery | pydantic-settings with required values and no defaults. `.env.example` is committed and `.env` is ignored. One `docker compose up` starts the API, worker, Postgres (the queue), Qdrant and the models declared in the Compose `models` element, served by Docker Model Runner. The frontend service arrives with the chat client feature, which completes this principle for the whole system | Pass (frontend deferred to its feature) |
| Engineering standards | uv, ruff (88, E W F I B C4 UP T20 G ASYNC), mypy strict with the pydantic plugin, pre-commit with the same checks as CI, keyword-only new parameters | Pass |
| Documentation standards | Google-style docstrings. ADRs in `docs/adr/` for the queue, the extractor, the local models and the chunking strategy. README with a diagram, setup, tests and the decision log | Pass |
| Development workflow | Spec Kit flow, Conventional Commits, `feature/` branch, squash merge. CI actions pinned by SHA and audited by zizmor | Pass |

**Post-design re-check (after Phase 1)**: all gates still pass. The two deviations from
"reuse before creating" are justified in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-async-pdf-ingestion/
├── plan.md              # This file
├── research.md          # Phase 0: decisions, alternatives, sources, measurements
├── data-model.md        # Phase 1: entities, state machine, validation rules
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   └── openapi.yaml     # Phase 1: REST contract
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml
├── uv.lock
├── .python-version
├── Dockerfile                    # multi-stage; one image for api, worker and migrate; Docling weights baked
├── alembic.ini
├── migrations/                   # Alembic revisions
├── src/multimodal_rag/
│   ├── shared/
│   │   ├── errors.py             # MultimodalRagError and failure families
│   │   ├── config.py             # Settings (pydantic-settings)
│   │   ├── logging.py            # structlog over stdlib, JSON in production
│   │   └── resilience.py         # retry policies (stamina) and timeouts
│   ├── ingestion/                # domain core and use cases: no framework imports
│   │   ├── domain.py             # Document, IngestionJob, ExtractedElement, BoundingBox, enums
│   │   ├── errors.py             # ingestion-specific errors
│   │   ├── ports.py              # Protocols listed in the Constitution Check
│   │   ├── retrieval_units.py    # structure-aware unit builder and figure units
│   │   ├── relationships.py      # caption, proximity and table-continuation rules
│   │   ├── figures.py            # relevance filter and identifier verification
│   │   └── use_cases/            # intake.py (SubmitDocument, GetJob), processing.py (ProcessJob),
│   │                             # library.py (ListDocuments, GetDocument, ListDocumentElements)
│   ├── adapters/
│   │   ├── http/                 # FastAPI app, routes, schemas, problem details, request id
│   │   ├── worker/               # claim loop, heartbeat, process recycling
│   │   ├── postgres/             # repositories and SKIP LOCKED job queue
│   │   ├── docling/              # extractor.py, mapping.py, headings.py, pdfium.py (PdfInspector)
│   │   ├── openai_compatible/    # FigureDescriber and Embedder over httpx
│   │   ├── qdrant/               # VectorIndex with dense and BM25 vectors
│   │   ├── tokenizer/            # TokenCounter over Hugging Face tokenizers
│   │   └── storage/              # filesystem BlobStorage
│   └── bootstrap.py              # composition root
└── tests/
    ├── fakes.py                  # one fake per port
    ├── unit/                     # domain, use cases, adapters with respx
    ├── integration/              # Postgres queue and Qdrant with testcontainers; Docling on fixtures
    ├── contract/                 # responses validated against contracts/openapi.yaml
    └── fixtures/                 # small generated PDFs (digital, scanned, split table)

compose.yaml                      # api, worker, migrate, postgres, qdrant + models (vlm, embedder)
.env.example
docs/adr/                         # 0001 queue, 0002 extractor, 0003 local models, 0004 chunking
```

**Structure Decision**: a web-service layout under `backend/`, leaving `frontend/` to the
chat client feature. Inside the package, code is grouped by concern:

- **`ingestion/`** is the feature's core (domain, ports and use cases).
- **`adapters/`** holds one folder per technology.
- **`shared/`** holds cross-cutting concerns.
- **`bootstrap.py`** is the only module that imports both the core and the adapters.

**Delivery split**: the repository tooling ships first in its own pull request
(`chore/scaffold-backend-tooling`). It contains the `backend/` package skeleton, uv with a
pinned interpreter, ruff, mypy, import-linter, pytest with the coverage gate, pre-commit,
GitHub Actions pinned by SHA with zizmor, and the base Dockerfile. The feature pull request
then contains only ingestion code, migrations, compose services and ADRs. This keeps one
concern per pull request (constitution, Development Workflow) and makes the feature
review smaller. `tasks.md` marks the setup phase as belonging to the tooling pull request.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Own job queue on Postgres (about 150 lines: claim, heartbeat, fencing, reaper) instead of a queue library | The spec requires prompt crash redelivery, three attempts that stay `processing`, and never two workers on one job | Celery with Redis duplicates tasks that outlive `visibility_timeout` and has no crash attempt counter. procrastinate has an open stale-worker overwrite bug and needs a periodic recovery task. Every library would still need our fencing in Postgres |
| Own structure-aware chunker instead of Docling's HybridChunker | The core must not import Docling. Units must include figure labels and cross-page table chains | HybridChunker drops picture labels unless a custom serializer is used, does not link table parts across pages, and would couple the core to Docling types |
| `compose.yaml` starts no frontend in this feature (Principle IX) | The chat client is its own feature, and this one delivers ingestion only | Adding a placeholder frontend now would ship an empty service with no requirement behind it. The chat client feature adds it to the same `compose.yaml` |
