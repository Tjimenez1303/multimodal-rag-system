# Backend architecture

## Bird's-eye view

The backend turns technical PDFs into searchable pieces and answers questions about them
with citations. Two kinds of work have very different costs, so they run in different
processes:

- The **API** is quick and stateless. It stores uploads, reports progress, serves the
  library and answers questions.
- The **worker** does the slow part. It reads every page with Docling, describes
  figures with a vision model, cuts the content into retrieval units, embeds them and
  indexes them in Qdrant.

PostgreSQL connects the two. It holds the documents and their extracted elements, and
its `ingestion_jobs` table is also the job queue. A Docker volume mounted in both
processes, the blob volume, holds the PDFs, the page images and the figure crops.

```
Browser ──> nginx ──> API ──┬──> PostgreSQL (documents, jobs, elements)
                            ├──> Qdrant (search)
                            ├──> Docker Model Runner (embedder, reranker, answer model)
                            └──> blob volume
                                       ▲
Worker ──── claims jobs from PostgreSQL ┘ ──> Docling, vision model, embedder, Qdrant
```

## Entry points

Everything starts in [`__main__.py`](../../backend/src/multimodal_rag/__main__.py):

| Command | What runs |
| --- | --- |
| `python -m multimodal_rag api` | uvicorn serving `bootstrap.create_api_app` |
| `python -m multimodal_rag worker` | `bootstrap.run_worker`, the claim loop |
| `python -m multimodal_rag worker-health` | The container healthcheck of the worker |
| `alembic upgrade head` | The migrations, run once by the `migrate` service |

## Layers

The code follows a hexagonal architecture (ports and adapters), grouped by feature.

| Layer | Package | Holds | May import |
| --- | --- | --- | --- |
| Composition root | `bootstrap.py` | The only place that builds adapters and injects them into use cases | Everything |
| Adapters | `adapters/` | FastAPI routes, the worker loop, PostgreSQL, Qdrant, model clients, Docling, storage | Cores, shared, any library |
| Answering core | `answering/` | Question answering: domain, ports, rules and the `AnswerQuestion` use case | Ingestion core, shared |
| Ingestion core | `ingestion/` | Ingestion and the library: domain, ports, rules and use cases | Shared |
| Shared | `shared/` | Settings, the error hierarchy, logging, retries, text helpers | Standard library and a few utilities |

Dependencies point inward only. A core never imports FastAPI, SQLAlchemy, httpx, Qdrant,
Docling or any other framework or SDK. It describes what it needs as a `typing.Protocol`
in its `ports.py`, and an adapter implements that protocol. The composition root picks
the adapter and passes it to the use case's constructor.

These rules are enforced, not just agreed on. [import-linter](https://import-linter.readthedocs.io)
runs in pre-commit and CI with three contracts declared in
[`pyproject.toml`](../../backend/pyproject.toml): the ingestion core imports no adapter,
framework or SDK, the answering core imports none either, and the layers above only
import downwards.

### Ports and use cases

A use case is a class with keyword-only constructor arguments, one per port it needs,
and an async `__call__`. For example, `DeleteDocument` receives a `DocumentRepository`,
a `JobQueue`, a `VectorIndex` and a `BlobStorage`, and knows nothing about PostgreSQL or
Qdrant. Tests build the same class with in-memory fakes.

| Port | Production adapter | Test fake |
| --- | --- | --- |
| `DocumentRepository`, `JobQueue`, `ElementRepository` | `PostgresDocumentRepository`, `PostgresJobQueue`, `PostgresElementRepository` | `InMemory*` |
| `BlobStorage` | `FilesystemBlobStorage` | `InMemoryBlobStorage` |
| `VectorIndex` | `QdrantVectorIndex` | `InMemoryVectorIndex` |
| `DocumentExtractor`, `PdfInspector` | `DoclingExtractor`, `PdfiumInspector` | `FakeExtractor`, `FakePdfInspector` |
| `Embedder`, `FigureDescriber` | `OpenAICompatibleEmbedder`, `OpenAICompatibleFigureDescriber` | `FakeEmbedder`, `FakeFigureDescriber` |
| `RelevanceJudge`, `AnswerGenerator` | `OpenAICompatibleRelevanceJudge`, `OpenAICompatibleAnswerGenerator` | `FakeRelevanceJudge`, `FakeAnswerGenerator` |
| `TokenCounter`, `LanguageIdentifier`, `AnswerSlots`, `Clock` | `HuggingFaceTokenCounter`, `Py3LangidIdentifier`, `AnyioAnswerSlots`, `SystemClock` | `WordTokenCounter`, `FakeLanguageIdentifier`, `FakeAnswerSlots`, `FrozenClock` |

A unit test, `test_fakes_match_ports.py`, checks that every fake still matches its port.

### Composition root

[`bootstrap.py`](../../backend/src/multimodal_rag/bootstrap.py) is the one module that
knows every concrete class.

- `create_api_app()` loads `ApiSettings`, then builds the use cases inside the FastAPI
  lifespan and yields them as state. Starlette copies that state into each request, and
  the providers in `adapters/http/dependencies.py` hand each route its use case through
  `Depends`.
- `run_worker()` loads `WorkerSettings`, loads the Docling models once, builds
  `ProcessJob` and runs `WorkerLoop` until SIGTERM or SIGINT. Docling is imported inside
  the worker path only, so the API never loads torch.

Swapping a provider, for example a different vector database, means writing one adapter
and changing one line here. Nothing under `ingestion/` or `answering/` changes.

## Cross-cutting concerns

### Settings

All settings come from environment variables through pydantic-settings, in
[`shared/config.py`](../../backend/src/multimodal_rag/shared/config.py). The classes
nest so each process asks only for what it uses: `DatabaseSettings` (migrations too),
`CommonSettings`, `ProviderSettings`, then `ApiSettings` and `WorkerSettings`. Required
settings have no default, and a missing or invalid one stops the process at startup with
a message naming every offending variable. Validators also check that limits fit
together, for example that each model timeout is shorter than the question deadline.

### Errors

Every error raised on purpose derives from `MultimodalRagError` in
[`shared/errors.py`](../../backend/src/multimodal_rag/shared/errors.py) and belongs to a
family (`ValidationError`, `NotFoundError`, `ProviderError`, `StorageError`, and so on).
Each class carries a stable `code` that clients can rely on. The feature errors live in
`ingestion/errors.py` and `answering/errors.py`.

The HTTP status of an error is decided in one place,
[`adapters/http/problems.py`](../../backend/src/multimodal_rag/adapters/http/problems.py),
by walking the error's class hierarchy. Every error response is an RFC 9457 problem
document with `code` and `request_id`. Internal details of unexpected server errors stay
in the logs.

### Timeouts and retries

Every external call has an explicit timeout from settings. Transient failures, meaning
an unreachable service, a timeout, 429 or a 5xx, are retried through
[`shared/resilience.py`](../../backend/src/multimodal_rag/shared/resilience.py), which
wraps [stamina](https://stamina.hynek.me) with exponential backoff and jitter. A
rejected request or an invalid answer fails at once, because repeating it cannot help.
The worker retries a failed claim without limit, since the database is its only source
of work.

### Logging and correlation

Modules log through `logging.getLogger(__name__)` with lazy `%s` arguments, and
structlog renders every record as one JSON object. `RequestContextMiddleware` gives each
request an `X-Request-ID` (reusing a safe one sent by the client) and writes one summary
line per request. The same id is stored on the job an upload creates, and the worker
binds it while processing, so one id follows a document from upload to indexing.

### Admission control

Answering is the most expensive request. `AnyioAnswerSlots` lets at most
`ANSWER_CONCURRENCY` questions run and `ANSWER_QUEUE_LIMIT` wait. Beyond that, the API
answers 503 with `Retry-After` at once instead of queueing without bound. The whole
question also runs under `ANSWER_DEADLINE_SECONDS`, and the work is cancelled when the
client disconnects.

## Invariants

- PDF processing never runs inside an HTTP request. An upload stores the file, enqueues a
  job and answers 202 with the job id.
- A job moves only through `pending`, `processing`, `completed` and `failed`, and every
  write by a worker is fenced by its lease token, so a worker that lost its lease can
  never overwrite the attempt that replaced it.
- A document has at most one job that has not failed, enforced by a partial unique index.
- New retrieval units stay hidden in Qdrant until the elements are stored, and become
  searchable together when the job publishes them.
- An answer is only shown with citations to passages the model was actually given.
- Element and unit ids are deterministic (UUIDv5 of the document fingerprint and a key),
  so a retried job overwrites what an earlier attempt wrote.

## Known gaps

- The answering use case and the vector index support restricting a question to some
  documents, but the HTTP body accepts only `question`, so the restriction cannot be
  requested over the API yet. `UnknownDocumentsError` and `DocumentsNotReadyError` exist
  for that feature and are not raised today.
- Conversation memory (follow-up questions) is not implemented. Each question is
  answered on its own.
