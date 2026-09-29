# Implementation Plan: Grounded Question Answering

**Branch**: `feature/grounded-question-answering` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-grounded-question-answering/spec.md`

## Summary

A technician posts a question to `POST /api/v1/questions` and receives, in the same
response, an answer built only from the completed documents. The answer carries numbered
citations, the retrieval units that were supplied, and the figure closest to the cited
text. The API process answers questions itself, because answering is an interactive
request, while ingestion stays in the worker.

- **Retrieval.** The existing Qdrant hybrid search fuses dense and BM25 results with RRF.
  Queries are embedded with Qwen3-Embedding's query instruction, and each hit also
  carries its dense cosine similarity, which Qdrant computes for the fused ids.
- **Relevance gate.** The model is asked only when a unit reaches `MIN_SIMILARITY` (0.60)
  or contains an identifier from the question verbatim. Otherwise the answer is "not
  enough information" at once, in the question's language.
- **Generation.** `ai/qwen3.5:9b`, the model ingestion already serves through Docker Model
  Runner, receives a prompt that the core builds, with instructions separated from fenced,
  numbered sources. Its output is constrained by a JSON schema to `answer` (Markdown with
  `[n]` markers) and `not_covered`.
- **Citations.** The core keeps only markers that point to supplied sources, merges units
  that share document and pages, and renumbers them. No other page can be cited.
- **Images.** The primary image is the figure of the most relevant cited unit that sits
  closest to its text. Other figures of the cited units are listed as related images, and
  decorative ones are never returned.
- **Resilience.** Every call has a timeout and bounded retries, and a 90-second deadline
  covers the whole question. At most 2 questions run at once and 10 wait, and further
  questions get 503 `answering_busy` at once. A client disconnect cancels the question and
  the generation.

Measured on the reference machine: search in about 10 ms, answers in 6 to 13 seconds, and
a similarity gap between relevant (0.648 and up) and unrelated questions (0.547 and down).
Decisions, alternatives and sources are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.14 (pinned patch in `.python-version`), managed with uv

**Primary Dependencies**:

- Already installed:
  - FastAPI 0.141 and pydantic-settings
  - httpx and stamina
  - qdrant-client 1.19
  - anyio, a Starlette dependency, for the admission limiter and the disconnect listener
- New: `py3langid` 0.4 (BSD-3), to pick the language of the fixed messages. It is the only
  new runtime dependency.

**Storage**: none new. The feature reads:

- **PostgreSQL**: documents, jobs, elements and relationships.
- **Qdrant**: retrieval units.
- **Blob volume**: figure crops, through the existing image route.

**Testing**:

- pytest, pytest-asyncio and pytest-cov, with fakes for every port and respx for the
  answer model adapter.
- testcontainers Qdrant for the similarity scores.
- Contract tests against the merged 001 and 002 OpenAPI files.
- A reference question set runs against the live system as a script, like the backlog
  load script, with its scoring functions unit-tested.

**Target Platform**: Linux containers through Docker Compose. The reference machine is an
Apple M4 Pro with Docker Desktop at 12 CPUs and 20 GB, and the models run on the host GPU
through Docker Model Runner (llama.cpp with Metal).

**Project Type**: web service. A new REST route runs in the existing API process, and the
chat client belongs to a later feature.

**Performance Goals**:

| Criterion | Target | Measured basis |
|---|---|---|
| SC-007 | 95% of answers in under 30 s | 6.1 to 13.0 s per answer, plus about 4 s when the model reloads |
| SC-008 | Specific error within the deadline, and uploads and status under 2 s | 90 s deadline. Ingestion routes share no code path with answering |
| SC-011 | Busy rejection in under 1 s | Rejected before any I/O |
| SC-009 | No accepted question exceeds the deadline while 100 documents queue | The worker process is separate, and the model's 4 slots are shared with figure description |

**Constraints**:

- Everything runs locally, and questions and documents never leave the machine (FR-025).
- The core imports no framework, SDK or provider.
- Questions and answers are not stored, and logs never contain the question, the answer or
  document content (FR-026).
- A question uses at most about 5,000 tokens of the model's shared 16,384-token KV cache.

**Scale/Scope**:

- One organization, no authentication.
- 2 questions answered at once and 10 waiting, both configurable.
- Libraries of at least 100 manuals, the ingestion target. Retrieval cost does not grow
  with the number of questions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Hexagonal architecture | `answering/` holds the domain, ports, prompt, gate, citations, image selection and the `AnswerQuestion` use case, importing only `ingestion` domain and ports, `shared` and the standard library. The route only translates HTTP. An import-linter `forbidden` contract covers `answering`, and the `layers` contract becomes bootstrap, adapters, answering, ingestion, shared | Pass |
| II. Ports and adapters | New ports: `AnswerGenerator`, `AnswerSlots` and `LanguageIdentifier`. Extended ports: `Embedder.embed_query`, `VectorIndex.search_hybrid` with similarity, and `get_many` on the element and document repositories. Each has a production adapter and a fake. Wiring happens only in `bootstrap.py`, and another provider needs a new adapter or only a new URL | Pass |
| III. Asynchronous ingestion | Unchanged. Answering never processes PDFs, and it runs in the API process, apart from the worker | Pass |
| IV. Multimodal fidelity | Reads the page, box and relationships stored at ingestion. Image selection uses the same top-left PDF-point convention | Pass |
| V. Grounded answers | Hybrid retrieval with documented RRF fusion (ingestion) and a relevance gate. The closest relevant image comes from spatial proximity. Instructions are separated from fenced sources, and the model answers only from them. Unit tests cover "not enough information" at the gate and from the model. Citations sit in a structured field, validated against the retrieved units. History and rendering belong to the chat client feature | Pass |
| VI. Resilience | Timeouts on the model, the embedder and Qdrant. Retries through `call_with_retry` with backoff and jitter, and a total deadline. Specific errors per component, a new `CapacityError` family, one HTTP mapping table, and no provider payloads in responses | Pass |
| VII. Observability | One structured log line per question with `request_id`, outcome, reason, units supplied, cited count, and search and generation times, without question, answer or content. Retries and busy rejections are logged at warning level | Pass |
| VIII. Test discipline | Fakes for every port, respx for the answer model adapter, no `MagicMock`. Behavior is asserted through the use case and the route. `tasks.md` includes tests per story, and the 90% coverage gate stays | Pass |
| IX. Configuration and delivery | New settings through pydantic-settings, with documented defaults in `.env.example`. Model URLs and names are required with no default and are injected by Compose. `docker compose up` stays the single start command, and the API binds the models already declared. The frontend arrives with the chat client feature | Pass (frontend deferred to its feature) |
| Engineering standards | uv, ruff, mypy strict, pre-commit. New parameters are keyword-only. Code is grouped under `answering/` by concern | Pass |
| Documentation standards | Google-style docstrings. ADR 0005 records the grounding and relevance gate strategy, and the README gains the question flow, a diagram update and the new settings | Pass |
| Development workflow | Spec Kit flow, Conventional Commits, `feature/` branch, squash merge | Pass |

**Post-design re-check (after Phase 1)**: all gates still pass. The design reuses the
ingestion adapters and error mapping, and the single new dependency is justified in
research section 9. The only deviation is the frontend deferral of Principle IX, carried
over from feature 001 and recorded in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-grounded-question-answering/
├── plan.md              # This file
├── research.md          # Phase 0: decisions, alternatives, sources, measurements
├── data-model.md        # Phase 1: answer entities, ports, validation rules
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   └── openapi.yaml     # Phase 1: askQuestion contract
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml                # + py3langid; import-linter contracts for answering
├── src/multimodal_rag/
│   ├── shared/
│   │   ├── errors.py             # + CapacityError family
│   │   ├── config.py             # ProviderSettings mixin; ApiSettings answering settings
│   │   └── resilience.py         # for_providers takes ProviderSettings
│   ├── ingestion/
│   │   ├── domain.py             # + BoundingBox.gap_to
│   │   └── ports.py              # Embedder.embed_query, SearchHit.similarity, get_many
│   ├── answering/                # domain core and use case: no framework imports
│   │   ├── domain.py             # Question, Answer, Citation, RetrievedSource, AnswerImage
│   │   ├── errors.py             # errors listed in research section 11
│   │   ├── ports.py              # AnswerGenerator, AnswerSlots, LanguageIdentifier
│   │   ├── prompting.py          # grounded prompt with fenced, numbered sources
│   │   ├── relevance.py          # similarity threshold and identifier rule
│   │   ├── citations.py          # marker validation, merging, renumbering
│   │   ├── images.py             # primary and related image selection
│   │   ├── sources.py            # source flags, tables and excerpts
│   │   ├── messages.py           # fixed not-enough-information messages (en, es)
│   │   └── use_cases/ask.py      # AnswerQuestion
│   ├── adapters/
│   │   ├── openai_compatible/
│   │   │   ├── answerer.py       # AnswerGenerator with a json_schema response format
│   │   │   ├── chat.py           # ChatCompletion model shared with describer.py
│   │   │   └── embedder.py       # + embed_query
│   │   ├── qdrant/index.py       # similarity per hit, missing collection means no hits
│   │   ├── postgres/             # documents.py and elements.py: get_many
│   │   ├── concurrency/anyio_slots.py        # AnswerSlots over anyio.CapacityLimiter
│   │   ├── language/py3langid_identifier.py  # LanguageIdentifier
│   │   └── http/
│   │       ├── routes_questions.py   # POST /api/v1/questions
│   │       ├── disconnect.py         # cancel the handler when the client leaves
│   │       ├── schemas.py            # + question and answer bodies
│   │       ├── dependencies.py       # + AnsweringState and provider
│   │       └── problems.py           # + answering errors, detail for their 5xx, Retry-After
│   └── bootstrap.py              # wires answering into the API app
└── tests/
    ├── fakes.py                  # + FakeAnswerGenerator, FakeAnswerSlots, FakeLanguageIdentifier
    ├── unit/answering/           # gate, prompt, citations, images, sources, use case
    ├── unit/adapters/            # answerer with respx, embedder query, slots, disconnect
    ├── integration/              # Qdrant similarity and missing collection
    ├── contract/                 # askQuestion against the merged contracts
    └── evaluation/               # reference_questions.yaml and run_reference.py

compose.yaml                      # api: models vlm and embedder, QDRANT_URL, answering settings
.env.example                      # answering settings documented
docs/adr/0005-grounded-answers-and-relevance-gate.md
README.md                         # question flow, diagram, settings
```

**Structure Decision**: the web-service layout of feature 001 is kept, and a new core
package `answering/` sits next to `ingestion/`. It depends on the ingestion domain and
ports, because retrieval units, elements and documents are ingestion's entities. It never
depends on ingestion use cases, and ingestion never depends on it. Adapters stay grouped
by technology, and the composition root is still the only module that sees both the core
and the adapters.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| `compose.yaml` still starts no frontend (Principle IX) | The chat client is its own feature, and this one delivers the question API only | A placeholder frontend would ship an empty service with no requirement behind it. The chat client feature adds it to the same `compose.yaml`, as feature 001 recorded |

The notable choices, each explained in research.md, are:

- A relevance gate in the core instead of trusting the model alone (section 3).
- The prompt built in the core instead of in the adapter (section 5).
- `py3langid` added for the fixed messages (section 9).
