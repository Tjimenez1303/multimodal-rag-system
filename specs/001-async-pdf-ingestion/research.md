# Research: Asynchronous PDF Ingestion

Every decision below was checked against official documentation, source code, release
notes or published benchmarks on 2026-09-28. Numbers marked as estimates were not measured
by their source or by this project. Measurements taken on the reference machine are listed
in the final section.

All runtime components run locally. The reference machine is an Apple M4 Pro (12 CPU
cores, 16 GPU cores, 48 GB) with Docker Desktop limited to 12 CPUs and 20 GB. Containers on
macOS get no GPU. Extraction therefore runs on container CPU, while the models run on the
host GPU through Docker Model Runner, with an Ollama container as the portable fallback.

## 1. Language and packaging

**Decision**: Python 3.14 (pinned patch in `.python-version`), managed with uv 0.12.x,
dependencies in `pyproject.toml` and a versioned `uv.lock`. PyTorch and torchvision resolve
from the PyTorch CPU index on Linux only.

**Rationale**: a wheels-only resolution of the full stack (docling 2.130, docling-parse,
torch 2.14 CPU, onnxruntime, rapidocr, qdrant-client, asyncpg, SQLAlchemy 2.1) succeeded
for Python 3.13 and 3.14 on both `aarch64` and `x86_64` manylinux. Python 3.15 is due on
2026-10-01 and is too new to pin. Without the CPU index, PyPI torch on Linux pulls about 22
CUDA packages even on arm64.

**Alternatives considered**: Python 3.13 (fully supported, older). Poetry or pip-tools
(the constitution mandates uv).

Sources: https://pypi.org/pypi/docling/json, https://download.pytorch.org/whl/cpu/torch/,
https://docs.astral.sh/uv/guides/integration/pytorch/, https://peps.python.org/pep-0790/

## 2. Job queue and job store

**Decision**: PostgreSQL 18 is both the job store and the queue. A worker claims a job
with `SELECT … FOR UPDATE SKIP LOCKED`, increments the attempt counter and sets a lease
token with an expiry. While the job runs, a heartbeat renews the lease. A job whose lease
expired is claimable again and keeps the `processing` state. A claim that would exceed the
attempt limit marks the job failed instead. Every write about the job (progress, results,
final state) is conditioned on the current lease token, which acts as a fencing token so a
stalled worker can never overwrite a job another worker took over. Workers wake up through
`LISTEN/NOTIFY` with a polling fallback.

**Rationale**:

- The clarified spec requires prompt redelivery after a crash, an attempt counter, three
  attempts and never two workers on the same job. A lease renewed by a heartbeat plus
  fencing satisfies all four on its own.
- Enqueueing is transactional with the document and job rows, so no dual write between a
  database and a broker can drift.
- Compose needs no extra service.
- The approach is established practice: Rails 8 made the Postgres-backed Solid Queue its
  default, and Supabase Queues builds on the same idea.

Its known limits (dead tuples, autovacuum tuning, polling load) matter at millions of jobs
per day, far above this workload.

**Alternatives considered**:

- **Celery with Redis.** Kombu emulates acknowledgements with a fixed `visibility_timeout`
  (default one hour) that is never extended while a task runs. A task that runs longer is
  redelivered and executes concurrently on another worker, and the Celery documentation
  itself warns it will run "again, and again in a loop". After a container crash the task
  only returns once the timeout elapses. Celery counts no crash redeliveries (only a
  boolean `redelivered`), and `task_reject_on_worker_lost` "can cause message loops".
  No fix exists in Celery 5.6.3 or Kombu 5.7.0a1. Meeting the spec would still need the
  lease, counter and fencing in Postgres, plus Redis.
- **Celery with RabbitMQ quorum queues.** Redelivers immediately on connection loss and
  counts deliveries, but `consumer_timeout` (30 minutes by default) must be raised for
  long jobs, fencing is still needed, and RabbitMQ adds a service.
- **procrastinate or pgqueuer.** Postgres-backed libraries. procrastinate needs a periodic
  task to retry stalled jobs and has an open issue where a stale worker can write to a job
  taken over by another (#1633).
- **arq** is in maintenance-only mode, and **Taskiq** is classified alpha.
- **Splitting jobs into short Celery subtasks** narrows the duplicate window without
  closing it, and adds chord orchestration and a result backend.

Sources:

- Celery and Kombu:
  - https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
  - https://docs.celeryq.dev/en/stable/userguide/tasks.html
  - https://github.com/celery/kombu/blob/v5.6.2/kombu/transport/redis.py
  - https://github.com/celery/celery/issues/5935
  - https://github.com/celery/celery/discussions/9963
- RabbitMQ:
  - https://www.rabbitmq.com/docs/consumers
  - https://www.rabbitmq.com/docs/quorum-queues
- Postgres-backed queues:
  - https://github.com/procrastinate-org/procrastinate/issues/1633
  - https://rubyonrails.org/2024/11/7/rails-8-no-paas-required
  - https://brandur.org/river
  - https://www.postgresql.org/docs/current/sql-select.html

## 3. Persistence access

**Decision**: SQLAlchemy 2.1 (async) over asyncpg, with Alembic migrations run by a
one-shot `migrate` service in compose. Documents carry `UNIQUE(sha256)`, and registration
uses `INSERT … ON CONFLICT (sha256) DO NOTHING RETURNING id`, falling back to a select of the
existing row.

**Rationale**: the unique constraint makes concurrent identical uploads resolve to a single
document without application locks (FR-016).

**Alternatives considered**: psycopg 3 as the driver, which is a valid runner-up. Raw SQL
without an ORM would add boilerplate for mapping.

Sources: https://www.postgresql.org/docs/current/sql-insert.html,
https://pypi.org/project/SQLAlchemy/, https://pypi.org/project/alembic/

## 4. File and image storage

**Decision**: a named Docker volume shared by the API and the worker, behind a
`BlobStorage` port with a filesystem adapter. Keys are content-addressed
(`documents/{sha256}.pdf`, `figures/{document_id}/{element_id}.png`), and writes go to a
temporary file followed by an atomic rename.

**Rationale**: it is the simplest option that works with one compose command. The port
keeps a later move to an S3-compatible store local to one adapter.

**Alternatives considered**: MinIO, whose repository is archived with no maintained image
on Docker Hub. SeaweedFS (Apache-2.0) is viable but adds a service that nothing needs yet.

Sources: https://github.com/minio/minio, https://github.com/seaweedfs/seaweedfs

## 5. Upload handling

**Decision**: FastAPI 0.141 with `multipart/form-data` uploads. The endpoint rejects early
when `Content-Length` exceeds 200 MB. It then copies the spooled upload into blob storage
in chunks, updating a SHA-256 hash and a byte counter on the way. A `PdfInspector` port
backed by pypdfium2 validates the file by content and reads its page count before the job
is created.

**Rationale**: multipart is what browsers and HTTP clients send by default. Starlette spools
the file to disk while parsing, so the extra hashing pass reads from local disk, which
takes well under a second for 200 MB and keeps SC-001 within reach. pypdfium2 is already a
Docling dependency and needs no rendering to count pages.

**Alternatives considered**: a raw `application/pdf` body read with `request.stream()`,
which hashes in a single pass but is less conventional for clients.

Sources: https://fastapi.tiangolo.com/tutorial/request-files/,
https://starlette.dev/requests/, https://pypi.org/project/pypdfium2/

## 6. Document extraction and OCR

**Decision**: the Docling library (2.130, MIT code and models) runs inside the worker,
behind a `DocumentExtractor` port. It uses RapidOCR for recognition, TableFormer for table
structure, and the figure classifier to tag logos and decorative images, with
`generate_picture_images` enabled to produce crops. The worker converts documents in page
batches, which lets it report progress per page and bounds memory. Model weights are
downloaded at image build time (`docling-tools models download`), so the worker starts
offline.

**Rationale**:

- Among parsers that meet every hard requirement, Docling is the only one that does: a
  permissive license on code and weights, a page and bounding box on every element, CPU
  execution in a linux/arm64 container, pluggable OCR with Spanish support, and weekly
  releases.
- Its OCR runs inside picture regions by default, and the labels become children of the
  picture item, which FR-024 needs.
- Its bounding boxes carry an explicit `coord_origin`. The PDF pipeline emits
  `BOTTOMLEFT`, so the adapter normalizes every box to `TOPLEFT` in PDF points.
- Docling 2.130 ships as `docling-slim`, so `onnxruntime` must be declared explicitly.
  Without it RapidOCR fails at startup with "onnxruntime is not installed", which the
  benchmark image build surfaced.

**Alternatives considered**:

- **Layout-grounded VLM parsers.** These lead OmniDocBench v1.6: PaddleOCR-VL-1.6 at 96.3,
  MinerU2.5-Pro at 95.8 and GLM-OCR at 95.2. They need a GPU or Metal to be practical, and
  MinerU's license adds user and revenue caps.
- **Marker, Surya and Chandra.** Their weights carry revenue-capped licenses.
- **olmOCR and Nanonets.** They output Markdown without boxes.
- **dots.ocr and DeepSeek-OCR.** They need CUDA.
- **docling-serve as a separate service.** It isolates memory growth but adds an HTTP hop
  and restricts pipeline options. The extractor port keeps it available as a swap.

If the benchmark shows weak tables or scanned pages, a later iteration can route only
those crops to PaddleOCR-VL-1.6 on the host, keeping Docling's page and box.

Sources:

- Docling:
  - https://github.com/docling-project/docling/releases
  - https://github.com/docling-project/docling/blob/main/docling/datamodel/pipeline_options.py
  - https://github.com/docling-project/docling/blob/main/docling/models/base_ocr_model.py
  - https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/base.py
  - https://arxiv.org/abs/2501.17887
- Benchmarks and alternatives:
  - https://github.com/opendatalab/OmniDocBench
  - https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6

## 7. Structure-aware retrieval units

**Decision**: the application layer owns a chunker that works on domain elements, not on
Docling objects. Units follow the reading order and break at headings, tables and figures.
Paragraphs under the same heading merge up to a token ceiling, and an oversize paragraph is
split only at sentence boundaries. Each table, or each chain of linked table parts across
pages, is one unit. Each relevant figure is one unit built from its caption, its labels and
its description. Units carry the heading path, the pages, the element ids and the related
figure ids. Tokens are counted through a `TokenCounter` port backed by the embedding
model's tokenizer.

**Rationale**:

- The domain core must not depend on Docling (Principle I), so Docling's HybridChunker
  cannot live in the core.
- HybridChunker also drops the labels inside pictures unless a custom serializer enables
  `traverse_pictures`, and it would not honor the cross-page table links the spec requires.
- Owning the chunker keeps chunking deterministic and testable with plain fakes.

**Alternatives considered**: Docling's HybridChunker called from the adapter. It is
rejected for the reasons above, but its rules (merge peers under the same headings, repeat
table headers, contextualize with headings) inform ours.

Sources:

- https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py
- https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/serializer/common.py

## 8. Tables that continue across pages

**Decision**: a domain rule links table B to table A when all of these hold:

- They are on consecutive pages.
- Only page furniture (headers, footers, page numbers) lies between them in reading order.
- They have the same column count.
- A ends in the lower part of its page and B starts in the upper part of its page.

A header row on B that repeats A's header is dropped when the parts are joined into the
retrieval unit. A caption containing "continued" or "continuación" strengthens the match
but is not required.

**Rationale**: Docling does not merge split tables today (issues #2976 and #2060 are open).
The rule follows Microsoft's documented cross-page table sample.

**Alternatives considered**: merging parts into a single element, which the clarification
rejected, and asking an LLM to decide, which is slower and less deterministic.

Sources: https://github.com/docling-project/docling/issues/2976, the cross-page table sample
at
[Azure-Samples/document-intelligence-code-samples](https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/Python(v4.0)/Retrieval_Augmented_Generation_(RAG)_samples/sample_identify_and_merge_cross_page_tables.py)

## 9. Figure description

**Decision**: the worker calls the vision model itself through a `FigureDescriber` port,
after extraction and outside Docling. The adapter speaks the OpenAI-compatible
`/chat/completions` API that both Docker Model Runner and Ollama expose, sending the figure
as a base64 `image_url` data URI with thinking disabled.

- **Scope.** Figures classified as logo, icon, signature, stamp, code or full-page image,
  and figures below 5% of the page area, are skipped. Full-page images come from scanned
  pages, where text recognition already provides the content.
- **Prompt.** The model receives the caption and the neighboring text, and is asked for a
  short description in the language of the caption and surrounding text (English when there
  is none) plus every printed label verbatim.
- **Input.** Images are downscaled to at most 1280 px on the long side.
- **Concurrency.** Two figures are described at a time, which measured fastest.
- **Resilience.** Each call has its own timeout and retry budget. When a figure still
  fails, it is marked `not_described` and the job continues (FR-027).
- **Verification.** Identifiers in the description (tokens that mix letters and digits,
  part-number patterns) are compared with the figure's labels and caption, and any not
  found are stored as unverified (FR-028).

**Rationale**: vendors converge on this pattern. Google's layout parser, Azure AI Search
image verbalization and Bedrock Data Automation each describe figures, keep the crop with
its page and box, and index the text. Calling the model through our own port gives
per-figure retries and timeouts, allows re-describing without re-parsing, and keeps tests
free of Docling. MMDocIR found that VLM-generated text retrieves better than OCR text,
while OCR keeps the exact tokens that keyword search needs. The benchmark confirmed the
need for context: on the 1972 scanned manual the model called a welder's control panel an
aircraft panel when it saw the image alone.

**Alternatives considered**: Docling's built-in `PictureDescriptionApiOptions`, which has a
single timeout and no per-figure degradation. Page-image retrieval (ColPali family) was
also considered but has no published Mac or CPU throughput and is left out of the baseline.

Sources:

- Vendor approaches:
  - https://learn.microsoft.com/en-us/azure/search/multimodal-search-overview
  - https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk
  - https://docs.aws.amazon.com/bedrock/latest/userguide/kb-multimodal-choose-approach.html
- Research:
  - https://arxiv.org/abs/2501.08828 (MMDocIR)
  - https://arxiv.org/abs/2601.08620 (ViDoRe v3)
- Image input format: https://www.docker.com/blog/how-to-use-multimodel-ai-with-model-runner/

## 10. Vision and language model

**Decision**: `ai/qwen3.5:9b` (Apache 2.0, Q4_K_M, 5.7 GB plus a 0.9 GB vision projector,
text and image input) is the default for figure descriptions, and later for answers, with
thinking disabled. The model reference is configuration.

**Rationale**:

- Newer Qwen releases publish no small sizes. Qwen 3.6 ships 27B and 35B-A3B, Qwen 3.7 is
  API-only, and Qwen 3.8 ships 27B.
- Qwen3.5-9B leads its size class on OCRBench (89.2) and OmniDocBench 1.5 (87.7) and
  supports 201 languages.
- On the reference machine through Docker Model Runner it described figures in 8.5 s on
  average, and in 6.0 s effective with two in parallel on digital pages (section 15).

**Alternatives considered**:

- `qwen3.5:4b`, the faster fallback (OCRBench 85.0).
- `qwen3.6:35b-a3b` (about 23 GB, 3B active parameters, OmniDocBench 89.9). It is the
  documented upgrade but was not measured.
- `gemma4:12b` (Apache 2.0), which still emits an empty thought block when thinking is
  off.
- Muse Glimmer 30B (Meta, Apache 2.0). It is dense, cannot turn reasoning off, and scores
  75.8 on OmniDocBench. Muse Spark has no open weights yet.
- DeepSeek V4 Flash (284B MoE, about 160 GB, text-only, vLLM on NVIDIA), which does not fit
  a laptop.
- `granite-vision-4.1`, which is English-only and extraction-oriented.

Sources:

- Qwen models:
  - https://huggingface.co/Qwen/Qwen3.5-9B
  - https://huggingface.co/Qwen/Qwen3.6-35B-A3B
  - https://github.com/QwenLM/Qwen3.8
- Muse Glimmer: https://huggingface.co/meta-models/Muse-Glimmer-30B
- Docker Hub: `docker model search qwen3.5` and `docker model search deepseek`, run on
  2026-09-28

## 11. Embeddings

**Decision**: `ai/qwen3-embedding:0.6b` (Apache 2.0, Q8_0, 639 MB, 1024 dimensions, 32k
context) behind an `Embedder` port that uses the OpenAI-compatible `/embeddings` API.
Passages are embedded without an instruction, and queries in later features use the
model's `Instruct: … Query:` format.

The model runs in embedding mode with `--ubatch-size 2048 --batch-size 2048`. With the
default physical batch of 512 tokens, llama.cpp crashed with HTTP 500 on inputs longer
than 512 tokens, which the benchmark reproduced. Retrieval units are also capped below
that ceiling by the chunker.

**Rationale**:

- The model scores 64.65 on MTEB multilingual retrieval with a clean zero-shot record,
  and costs the same as the 0.6B alternatives.
- It produced 25.9 passages per second on Metal against 2.6 on container CPU.
- The maintainer chose it over microsoft/harrier-oss-v1-0.6b, which scores 70.75 but
  trained on part of the benchmark data. Both use 1024 dimensions, so switching later
  changes no index schema.

**Alternatives considered**:

- `Qwen3-Embedding-4B` (69.60), about six times slower.
- `bge-m3` (MIT), which scores lower.
- `embeddinggemma`, which is under Gemma terms.
- jina v5, which is non-commercial.

Sources:

- MTEB multilingual leaderboard: https://mteb-leaderboard.hf.space/benchmark/MTEB(Multilingual%2C%20v2)
- Model cards:
  - https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
  - https://huggingface.co/microsoft/harrier-oss-v1-0.6b
- Batch sizing: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

## 12. Vector index and keyword side

**Decision**: Qdrant 1.19 with one collection. Each point carries a named dense vector
(cosine, 1024 dimensions) and a named sparse vector computed by Qdrant's server-side BM25
with the IDF modifier, so hybrid search later fuses the two with RRF.

- **Point ids.** Deterministic: `uuid5(ID_NAMESPACE, "unit:{sha256}:{unit_key}")`, where
  `ID_NAMESPACE` is a random UUID generated once, as RFC 9562 section 6.6 recommends.
- **Payload indexes.** `document_id`, `unit_type`, `pages` and `visible` are indexed
  before the first insert.
- **Visibility.** Points are written with `visible=false` and flipped to `true` in one
  filtered `set_payload` when the job completes. A failed job deletes its points by
  `document_id` (FR-018).
- **BM25 options.** Language-neutral: lowercase, ASCII folding and no stemming. The same
  analyzer then works for English and Spanish queries, and identifiers such as part
  numbers match exactly.

**Rationale**: server-side BM25 has been in open-source Qdrant core since 1.15.2, so no
sparse model runs in the worker. Deterministic ids make re-processing overwrite points
instead of duplicating them (FR-015, SC-008). A learned sparse model
(opensearch-neural-sparse-multilingual-v1) beats BM25 on MIRACL-es and stays a candidate if
the evaluation shows lexical recall gaps.

**Alternatives considered**:

- Chroma, whose sparse search is cloud-only.
- Weaviate and Milvus, which are viable but heavier or less aligned with server-side BM25.
- fastembed BM25 computed client-side, the runner-up.

To verify during setup: the exact option names for a language-neutral analyzer in Qdrant's
BM25 inference.

Sources:

- https://github.com/qdrant/qdrant/releases/tag/v1.15.2
- https://qdrant.tech/documentation/search/hybrid-queries/
- https://qdrant.tech/documentation/manage-data/points/
- https://qdrant.tech/documentation/manage-data/indexing/

## 13. Model serving

**Decision**: Docker Model Runner (DMR) serves both models by default. The Compose `models`
top-level element declares them, and `docker compose up` pulls them and applies their
runtime flags:

- **Vision model.** Thinking disabled with
  `--chat-template-kwargs {"enable_thinking": false}`.
- **Embedding model.** Embedding mode, with the larger batch from section 11.

Compose injects each model's URL and name into the worker, which reaches DMR at
`http://model-runner.docker.internal/engines/v1`. The adapter also sends
`chat_template_kwargs` on every request, as a second guard against thinking.

DMR must be enabled once per machine:

- **macOS and Windows.** `docker desktop enable model-runner --tcp 12434 --cors none`.
- **Linux.** Install the `docker-model-plugin` package.

Without DMR, Compose stops at startup with an explicit error. An override file,
`compose.ollama.yaml`, replaces the models with an Ollama container plus a one-shot pull
service. Because the adapter speaks the OpenAI-compatible API, the same adapter works with
both providers, and only the base URL and model names change.

**Rationale**:

- **Speed.** On macOS, containers get no GPU. DMR runs llama.cpp as a host process with
  Metal, which measured 4 times faster for figure descriptions and 10 times faster for
  embeddings than Ollama inside a container (section 15).
- **Memory.** DMR uses the Mac's unified memory, not the Docker VM's limit.
- **One command.** It keeps `docker compose up` as the single start command, and needs no
  separate Ollama install.

**Alternatives considered**:

- **Ollama in a container as the default.** Portable, but CPU-only on macOS: about 35 s
  per figure and 2.6 passages per second.
- **Native Ollama on the host.** Performance similar to DMR according to published
  comparisons, but it is an extra install outside Docker.
- **vllm-metal in DMR.** Docker reports it about 1.2 times slower than llama.cpp.

Sources:

- Docker Model Runner:
  - https://docs.docker.com/ai/model-runner/
  - https://docs.docker.com/ai/model-runner/api-reference/
  - https://github.com/docker/model-runner/blob/main/pkg/inference/runtime_flags_allowlist.go
  - https://www.docker.com/blog/docker-model-runner-vllm-metal-macos/
- Compose:
  - https://docs.docker.com/compose/how-tos/models-and-compose/
  - https://github.com/docker/compose/blob/main/pkg/compose/model.go
- Ollama: https://docs.ollama.com/faq

## 14. Cross-cutting libraries

| Concern | Decision | Runner-up | Source |
|---|---|---|---|
| Structured logging | structlog 26.x configured over stdlib: `ProcessorFormatter` renders `logging.getLogger(__name__)` records as JSON, `PositionalArgumentsFormatter` keeps lazy `%s`, and `merge_contextvars` injects correlation ids | python-json-logger 4.x | https://www.structlog.org/en/stable/standard-library.html |
| Correlation id | Middleware reads or creates `X-Request-ID`. The id is stored on the job row and rebound in the worker together with `job_id` | asgi-correlation-id 5.x | https://github.com/snok/asgi-correlation-id |
| Retries | stamina 26.x (tenacity underneath) with exponential backoff and jitter, retrying only transient errors, and a testing switch to disable retries | tenacity | https://stamina.hynek.me/en/stable/ |
| Settings | pydantic-settings, with required values that have no default | none | https://docs.pydantic.dev/latest/concepts/pydantic_settings/ |
| Import boundaries | import-linter 2.15 with `forbidden` and `layers` contracts | tach | https://import-linter.readthedocs.io/en/stable/ |
| HTTP client for adapters | httpx, tested with respx | none | https://www.python-httpx.org/, https://lundberg.github.io/respx/ |
| Container build | Official uv multi-stage Dockerfile with cache mounts, `uv sync --locked` and a non-root user | none | https://docs.astral.sh/uv/guides/integration/docker/ |

No maintained async circuit breaker was found (pybreaker has no asyncio support, and
purgatory has had no release since 2024-11), so resilience relies on timeouts plus
bounded retries with backoff and jitter, which Principle VI allows.

## 15. Measurements on the reference machine

**Setup**: Apple M4 Pro with Docker Desktop 4.93 (12 CPUs, 20 GB) on 2026-09-28. The
extraction container was limited to 8 CPUs and 10 GB, with Docling 2.130, RapidOCR on
onnxruntime, TableFormer, the figure classifier and `images_scale=2.0`. Model runs used
Docker Model Runner with llama.cpp on Metal, and Ollama 0.34.4 inside a container on 8
CPUs for comparison.

**Samples** are in `docs/samples/`, which git ignores:

- FAA-H-8083-32B chapter 4: digital, 71 pages, English.
- INSST electrical risk guide: digital, 86 pages, Spanish.
- US Army TM 5-3431-201-10: scanned, 65 pages, English.

**Extraction**:

| Document | Pages | Seconds | s/page | Projected 100 pages | Tables | Figures |
|---|---|---|---|---|---|---|
| FAA (digital) | 71 | 105.3 | 1.48 | 2.5 min | 8 | 117 |
| INSST (digital) | 86 | 148.6 | 1.73 | 2.9 min | 21 | 50 |
| TM 5-3431 (scanned) | 65 | 207.0 | 3.18 | 5.3 min | 19 | 98 |

**Spanish text recognition**: ten INSST pages were rendered at 200 dpi into an image-only
PDF and compared with the original text layer (5,629 words).

| Engine | Word recall | Accented word recall | s/page |
|---|---|---|---|
| RapidOCR default models | 0.975 | 0.948 | 3.41 |
| RapidOCR with `Rec.lang_type=LATIN` | 0.975 | 0.948 | 3.54 |
| Tesseract `spa+eng` | 0.956 | 0.932 | 2.98 |

The LATIN variant produced byte-identical output, so the parameter did not reach RapidOCR
through Docling. The default models already meet SC-009.

**Figure description (`qwen3.5:9b`)**:

| Runtime | Scope | Mean s/figure | Notes |
|---|---|---|---|
| Ollama in container (CPU) | 18 figures, all samples | 34.7 (median 32.2) | Too slow for SC-011 |
| DMR, Metal | 17 figures, all samples | 8.5 (median 7.6) | Warm-up 9.5 s. No reasoning in any response |
| DMR, Metal | 11 digital figures | 6.8 | |
| DMR, Metal | 6 scanned figures | 11.7 | Larger images and more text |
| DMR, Metal, 2 in parallel | 16 digital figures | 6.0 effective | Best throughput |
| DMR, Metal, 4 in parallel | 16 digital figures | 7.0 effective | GPU saturated |

**Embeddings (`qwen3-embedding:0.6b`, 256 passages of about 100 words)**:

| Runtime | Seconds | Passages/s |
|---|---|---|
| Ollama in container (CPU) | 97.1 | 2.6 |
| DMR, Metal, batch 2048 | 9.9 | 25.9 |

**Findings that changed the plan**:

- Figure description and embeddings must run on the host accelerator. On container CPU,
  embeddings alone would push a 100-page manual past SC-003.
- Embedding mode needs a physical batch larger than the longest unit.
- On scanned pages Docling classifies some regions as `full_page_image` and tags Google
  digitization marks as `logo`. Both must be excluded from description.
- Without context, the vision model sometimes misidentifies the equipment in old scans.
  The prompt includes the caption and the neighboring text, and FR-028 flags invented
  identifiers.
- `docling` 2.130 requires an explicit `onnxruntime` dependency for RapidOCR.

**Resulting targets**:

| Criterion | Measured or projected | Status |
|---|---|---|
| SC-003 | About 2.7 min (extraction plus embeddings) | Met |
| SC-010 | About 5.5 min | Met |
| SC-011 | 6.0 s effective on digital pages, about 10 s on scanned pages | Met (8 s target) |
| SC-009 | 97.5% word recall | Met |
