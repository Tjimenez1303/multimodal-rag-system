# Backend codemap

A map of `backend/`, one heading per folder and file, in the order the dependencies
point: shared code first, then the two cores, then the adapters and the composition
root. Each entry says what the code is for and names the symbols worth searching for.
Paths under the package are relative to `backend/src/multimodal_rag/`.

## Project root

| Path | Purpose |
| --- | --- |
| `pyproject.toml` | Dependencies, ruff, mypy, pytest, coverage and the import-linter contracts |
| `uv.lock` | Locked dependency versions |
| `Dockerfile` | One image for the API, the worker and the migrations, with the Docling models and the embedding tokenizer baked in |
| `docling_models.txt`, `embedder_tokenizer.txt` | Model lists shared by the Dockerfile and CI |
| `alembic.ini`, `migrations/` | Database migrations |
| `scripts/export_openapi.py` | Writes `frontend/openapi.json`, the input of the generated client |
| `tests/` | Unit, contract, integration, evaluation and load tests, see [Testing](testing.md) |

## Package root

### `__init__.py`

Package docstring and `__version__`, read from the installed package metadata.

### `__main__.py`

The command line: `python -m multimodal_rag {api,worker,worker-health}`. The `api` role
starts uvicorn with the app factory, `worker` runs the claim loop, and `worker-health` is
the container healthcheck.

### `bootstrap.py`

The composition root, the only module that builds adapters and wires them into use
cases. `create_api_app` builds the API and its lifespan state, `run_worker` runs the
worker until a termination signal, and `worker_is_alive` backs the healthcheck. Any new
adapter or use case is wired here.

## `shared/`

Cross-cutting code that every layer may import. It holds no business rule.

| File | Purpose | Key symbols |
| --- | --- | --- |
| `config.py` | Settings from environment variables, one class per process | `DatabaseSettings`, `CommonSettings`, `ProviderSettings`, `ApiSettings`, `WorkerSettings`, `load()` |
| `errors.py` | Root of the error hierarchy and its families, each with a stable `code` | `MultimodalRagError`, `ValidationError`, `NotFoundError`, `ProviderError`, `StorageError`, `CapacityError` |
| `logging.py` | structlog over the standard library, JSON or console output, correlation ids | `configure_logging`, `bind_correlation`, `clear_correlation` |
| `resilience.py` | Retries with exponential backoff and jitter on stamina | `RetryPolicy.for_providers`, `RetryPolicy.for_claims`, `call_with_retry` |
| `text.py` | Sentence splitting and accent-insensitive folding shared by both cores | `split_sentences`, `fold` |

## `ingestion/`

The ingestion core: turning a PDF into stored elements and searchable units, and the
library around them. It imports no framework, SDK or database client.

| File | Purpose | Key symbols |
| --- | --- | --- |
| `domain.py` | Entities and value objects, including the job state machine and deterministic ids | `Document`, `IngestionJob` (`claim`, `advance`, `complete`, `fail`), `ExtractedElement`, `ElementRelationship`, `RetrievalUnit`, `BoundingBox`, `JobStatus`, `JobStage`, `element_id_for`, `unit_id_for` |
| `errors.py` | One error per root cause of ingestion | `FileTooLargeError`, `UnsupportedMediaTypeError`, `PageLimitExceededError`, `EncryptedDocumentError`, `LeaseLostError`, `DocumentNotFoundError`, `IngestionInProgressError` |
| `ports.py` | The interfaces the core needs, and the values passed across them | `DocumentRepository`, `JobQueue`, `ElementRepository`, `BlobStorage`, `PdfInspector`, `DocumentExtractor`, `FigureDescriber`, `Embedder`, `TokenCounter`, `VectorIndex`, `Clock`, `Page`, `ExtractionBatch`, `SearchHit` |
| `figures.py` | Which images are decorative, which are described, and what a description may claim | `FigurePolicy.triage`, `description_context`, `unverified_identifiers` |
| `relationships.py` | Links between elements: captions, nearby text, tables continued on the next page | `link_elements`, `repeats_header` |
| `retrieval_units.py` | Structure-aware chunking under a token ceiling, tables and figures kept whole | `build_units` |

### `ingestion/use_cases/`

| File | Runs in | Use cases |
| --- | --- | --- |
| `intake.py` | API | `SubmitDocument` (store, register, enqueue), `GetJob` |
| `library.py` | API | `ListDocuments`, `GetDocument`, `ListDocumentElements`, `GetElementImage`, `GetPageImage`, `DeleteDocument` |
| `processing.py` | Worker | `ProcessJob`, the whole pipeline from extraction to publishing |

## `answering/`

The answering core: from a question to a grounded answer with citations and figures. It
reuses the ingestion ports for search and storage, and adds its own for the models.

| File | Purpose | Key symbols |
| --- | --- | --- |
| `domain.py` | Questions, answers and what they carry | `Question.create`, `Answer`, `AnswerStatus`, `NotEnoughReason`, `Citation`, `RetrievedSource`, `AnswerImage`, `JudgedHit`, `GroundedPrompt` |
| `errors.py` | Answering failures, named after the failing component | `InvalidQuestionError`, `AnsweringBusyError`, `Search*Error`, `Reranker*Error`, `AnswerModel*Error`, `AnswerDeadlineExceededError` |
| `ports.py` | Model and admission interfaces | `RelevanceJudge`, `AnswerGenerator`, `AnswerSlots`, `LanguageIdentifier` |
| `relevance.py` | The relevance gate and identifier pinning | `distinct_hits`, `rank_by_relevance`, `passes_gate`, `question_identifiers` |
| `prompting.py` | The grounded prompt and its rules | `build_prompt`, `SYSTEM_RULES` |
| `citations.py` | Validating and renumbering the `[n]` markers the model writes | `resolve_citations`, `has_markers` |
| `attribution.py` | Adding markers to an answer written without any | `find_statements`, `attribute` |
| `sources.py` | The list of passages returned with an answer | `assemble_sources`, `elements_of` |
| `images.py` | Choosing the primary and related figures | `select_images`, `figure_ids_of` |
| `messages.py` | Fixed not-enough-information messages in English and Spanish | `not_enough_message` |
| `use_cases/ask.py` | The question-answering use case | `AnswerQuestion`, `AnsweringOptions` |

## `adapters/`

Implementations of the ports, plus the two driving adapters (HTTP and the worker loop).
This is the only layer that imports frameworks and SDKs.

### `adapters/http/`

The FastAPI application. Routes only translate HTTP into use case calls and back.

| File | Purpose |
| --- | --- |
| `app.py` | `create_app`, the health routes and the OpenAPI post-processing |
| `routes_ingestion.py` | `POST /api/v1/documents` and `GET /api/v1/jobs/{job_id}` |
| `routes_documents.py` | Library, elements, figure crops, page images and deletion |
| `routes_questions.py` | `POST /api/v1/questions` |
| `schemas.py` | Pydantic request and response bodies, each with a `from_*` mapper from the domain |
| `dependencies.py` | Lifespan state types and the `Depends` providers that hand use cases to routes |
| `problems.py` | The single error-to-status mapping and RFC 9457 problem responses |
| `request_context.py` | `RequestContextMiddleware`: `X-Request-ID` and one log line per request |
| `body_limit.py` | `BodySizeLimitMiddleware`: 413 before an oversized body is parsed |
| `disconnect.py` | `run_until_disconnect`: cancels work when the client leaves |

### `adapters/postgres/`

| File | Purpose |
| --- | --- |
| `tables.py` | SQLAlchemy Core schema shared by the repositories and Alembic |
| `engine.py` | Engines, transactions and the translation of driver errors into storage errors |
| `documents.py` | `PostgresDocumentRepository` |
| `elements.py` | `PostgresElementRepository`, replacing a document's elements in one fenced transaction |
| `job_queue.py` | `PostgresJobQueue`: enqueue, `SKIP LOCKED` claims, leases, heartbeats and fenced updates (`lock_leased_job`) |
| `job_notifications.py` | `PostgresJobNotifications`: a `LISTEN` connection that wakes idle workers |
| `pagination.py` | Opaque keyset cursors |

### `adapters/qdrant/`

`index.py` holds `QdrantVectorIndex`: the collection with a dense cosine vector and a
server-side BM25 sparse vector, hidden upserts, publishing, deletion and hybrid search
fused with RRF.

### `adapters/openai_compatible/`

HTTP clients for models served in the OpenAI API format by Docker Model Runner. No
OpenAI SDK is used, only httpx.

| File | Purpose |
| --- | --- |
| `transport.py` | `post_json`: one request with retries and response validation |
| `chat.py` | The parts of a `chat/completions` answer the clients read |
| `embedder.py` | `OpenAICompatibleEmbedder` for passages and queries |
| `reranker.py` | `OpenAICompatibleRelevanceJudge`, the Qwen3 reranker scored with log probabilities |
| `answerer.py` | `OpenAICompatibleAnswerGenerator` with a strict JSON schema |
| `describer.py` | `OpenAICompatibleFigureDescriber`, the vision model that describes figures |

### `adapters/docling/`

| File | Purpose |
| --- | --- |
| `extractor.py` | `DoclingExtractor`: converts page batches with OCR, tables and figure classification |
| `mapping.py` | `map_document`: Docling items to domain elements, crops and caption links |
| `headings.py` | `HeadingLevels`: heading depth from the PDF outline or the section number |
| `pdfium.py` | `PdfiumInspector` for upload validation, and `read_layout` for page facts |

### Other adapters

| Path | Purpose |
| --- | --- |
| `storage/filesystem.py` | `FilesystemBlobStorage`: atomic writes under the blob root |
| `worker/loop.py` | `WorkerLoop`: claim, heartbeat, run and stop handling |
| `worker/liveness.py` | `LivenessFile`, touched while the worker's event loop runs |
| `tokenizer/huggingface.py` | `HuggingFaceTokenCounter` with the embedding model's tokenizer |
| `language/py3langid_identifier.py` | `Py3LangidIdentifier` for the language of a question |
| `concurrency/anyio_slots.py` | `AnyioAnswerSlots`, admission control for questions |
| `provider_errors.py` | Classifies HTTP failures as unavailable, timeout or rejected |
| `clock.py` | `SystemClock` |

## `migrations/`

| Path | Purpose |
| --- | --- |
| `env.py` | Runs migrations with the async engine and the same settings as the application |
| `versions/0001_initial_schema.py` | The four tables and the job notification trigger |
| `versions/0002_one_active_job_per_document.py` | Partial unique index: one job that has not failed per document |
| `versions/0003_unique_reading_order_and_claim_index.py` | Unique reading order per document and the index that serves claims |
| `versions/0004_index_relationships_by_target.py` | Index for looking relationships up by target |
