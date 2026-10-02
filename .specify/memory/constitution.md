# multimodal-rag-system Constitution

## Core Principles

### I. Hexagonal Architecture

- The codebase MUST be organized into a domain core (entities, value objects, RAG use cases),
  ports (abstract interfaces owned by the core), inbound adapters (REST API, worker entry
  points) and outbound adapters (LLM, embeddings, vector DB, PDF extraction, job store, queue).
- The domain core and the use cases MUST NOT import FastAPI, pydantic-settings, any provider
  SDK, any vector DB client or any PDF library. Dependencies point inward only.
- The REST layer MUST only translate HTTP to use case calls and results back to HTTP. It MUST
  NOT contain retrieval, prompting or extraction logic.
- An automated import-boundary check MUST run in CI and fail when the core imports an adapter,
  a framework or an SDK.

Rationale: a core free of frameworks stays maintainable and testable as providers and
transports change.

### II. Ports and Adapters

- The LLM, embeddings, vector store, PDF extractor, job repository and task queue MUST each be
  reached only through a port defined in the core (`typing.Protocol` or `abc.ABC`).
- Concrete adapters MUST be selected by configuration and wired in a single composition root
  (a factory or registry). Use cases receive their ports through constructor injection and
  MUST NOT instantiate adapters themselves.
- Replacing OpenAI with Ollama (or one vector DB with another) MUST require only a new adapter
  plus a configuration change, with zero edits under the core package. Every port MUST have at
  least two implementations: one production adapter and one test fake.

Rationale: swappable providers are an explicit evaluation criterion and the basis of isolated
tests.

### III. Asynchronous Ingestion

- PDF extraction, chunking, embedding and indexing MUST NOT run inside the HTTP request that
  receives the upload. The upload endpoint MUST persist the file, enqueue a job and respond
  with `202 Accepted` and a unique `job_id`.
- Jobs MUST move only through the states `pending`, `processing`, `completed` and `failed`.
  State, progress (processed over total pages or steps) and the failure reason MUST be
  persisted outside the worker process and exposed through a status endpoint.
- Workers MUST run as a separate process from the API so that ingestion load never degrades
  query latency, and MUST scale horizontally by adding worker replicas.
- Job execution MUST be idempotent: re-running a job for the same document MUST NOT create
  duplicate chunks in the vector store.

Rationale: heavy extraction must not make the API collapse or time out, including when many
manuals are ingested at once.

### IV. Multimodal Fidelity

- Extraction MUST produce typed elements (text, table, image) and every element MUST carry
  its source document identifier, page number and bounding box.
- Bounding boxes MUST declare their unit and coordinate origin in the schema (for example PDF
  points with a top-left origin), and one convention MUST be used across the whole system.
- The relationship between text, tables and nearby images (same page, spatial proximity,
  captions) MUST be computed at ingestion time and stored with the chunk metadata.
- Chunking MUST follow document semantics or layout (sections, headings, tables, captions).
  Splitting purely by a fixed number of characters or tokens is forbidden. A size limit MAY
  only act as a secondary cap inside a semantic unit.

Rationale: page and spatial metadata are what allow an answer to point at the right image
and page.

### V. Grounded Answers

- Retrieval MUST be hybrid, combining dense semantic search with keyword search (for example
  BM25 or sparse vectors) and a documented fusion strategy.
- For each retrieved chunk the system MUST resolve whether it has associated images and MUST
  return the closest relevant image, selected by spatial proximity to the supporting text.
- Prompts MUST instruct the model to answer only from the supplied context and to separate
  instructions from retrieved content. When the context is insufficient the system MUST say
  so explicitly instead of guessing, and this behavior MUST be covered by a test.
- Every answer MUST cite the source document name and page for each piece of supporting
  context in a structured field of the response, not only inside free text.
- The client MUST keep the conversation history, render Markdown and display the citation and
  the related image next to the answer it supports.

Rationale: users trust a technical answer only when they can see where it came from and the
diagram it refers to.

### VI. Resilience and Error Handling

- Every call to an external service (LLM, embeddings, vector DB, queue, object storage) MUST
  have an explicit timeout.
- Transient failures (network errors, timeouts, HTTP 429 and 5xx) MUST be retried with
  exponential backoff and jitter, or guarded by a circuit breaker. Non-transient errors MUST
  NOT be retried. Timeouts, retry counts and backoff bounds MUST be configurable with
  documented defaults.
- The project MUST define one root exception with a subclass per failure family (for example
  configuration, extraction, provider, storage, not found, validation), and each distinct root
  cause MUST raise its own specific error.
- Data inconsistencies (an indexed chunk without its document, an invalid state transition)
  MUST surface as internal errors and MUST NOT be silently skipped or defaulted.
- Bare `except:` and `except Exception: pass` are forbidden. Errors are mapped to HTTP status
  codes in one place in the REST adapter, and responses MUST NOT leak stack traces or
  provider payloads.

Rationale: network drops, rate limits and slow models are expected conditions and must fail
in predictable, diagnosable ways.

### VII. Observability

- Production logging MUST emit structured JSON with timestamp, level, logger name, message
  and a correlation ID. The request ID MUST propagate from the API into the job payload so
  that worker logs share it with the originating request, and job logs MUST include `job_id`.
- Every module MUST obtain its logger with `logging.getLogger(__name__)`.
- Log calls MUST use lazy `%s` formatting. f-strings and `str.format` inside log calls are
  forbidden and are enforced by ruff rule family G.
- Logs MUST NOT contain secrets, API keys, tokens, full prompts with user content or other
  PII. Critical operations (upload, job transitions, retrieval, generation, retries) MUST be
  logged at an appropriate level.

Rationale: operations and errors must be traceable end to end without exposing sensitive
data.

### VIII. Test Discipline

- Unit tests MUST isolate third-party components with fakes that implement the ports (a fake
  LLM, an in-memory vector store, a fake extractor). HTTP adapters MUST be tested with
  `respx`. `unittest.mock.MagicMock` and `Mock` MUST NOT be used.
- Tests MUST assert observable behavior through public interfaces, not private attributes or
  call sequences.
- Every bug fix MUST include a test that fails before the fix and passes after it.
- Every feature task list MUST include test tasks, and CI MUST fail when backend line coverage
  drops below 90%. The client SHOULD have tests for citation and image rendering.

Rationale: generative components are non-deterministic, so the surrounding logic must be
proven with deterministic doubles.

### IX. Configuration and Delivery

- Settings MUST be loaded with pydantic-settings from environment variables. `.env.example`
  MUST be committed with every variable documented, and `.env` MUST be git-ignored.
- Required settings MUST have no default, and the application MUST fail at startup with a
  clear message when one is missing. Environment-specific values (local, test, production)
  MUST come from the environment, never from code branches.
- A single `docker compose up` MUST start the API, worker, frontend, vector DB and queue with
  health checks, and the README MUST document that command.

Rationale: a reviewer must be able to run the whole system in one step, and a misconfigured
deployment must fail loudly instead of running with wrong values.

## Engineering Standards

- Python MUST be managed only with uv, with a pinned interpreter version, dependencies
  declared in `pyproject.toml` and a versioned `uv.lock`.
- ruff MUST be the linter and formatter with line length 88 and the rule families E, W, F, I,
  B, C4, UP, T20, G and ASYNC. mypy MUST run in strict mode with the pydantic plugin.
- Application code MUST NOT use `print`. Public functions MUST have modern type hints
  (`list[str]`, `X | None`), and parameters added to existing functions MUST be keyword-only.
- pre-commit MUST run the same checks as CI: ruff (lint and format), mypy, typos,
  detect-private-key, end-of-file-fixer and trailing-whitespace.
- Defects MUST be fixed at their root cause. Existing code MUST be reused before new code is
  created, and a pattern change MUST be applied everywhere the pattern occurs.
- Code MUST be grouped by feature or concern, and files holding a single trivial function
  SHOULD be avoided. Names MUST describe what an artifact is or does, never the ticket or bug
  that motivated it.
- A function approaching 40 lines SHOULD be split. Tooling MUST be official and current, and
  the frontend MUST use the official linter and formatter of its chosen framework.

## Documentation Standards

- Every public module, class and function MUST have a Google-style docstring with Args,
  Returns and Raises sections as applicable. Types belong in the signature, and examples are
  included only when they add clarity.
- Inline comments MUST be one line. A comment above each logical step of a function body
  names what the step achieves, and when the step calls another function it says what the
  call is for. Non-obvious code also gets a comment explaining why it is there. Comments MUST
  NOT reference tickets or bugs.
- The README MUST contain a logical architecture diagram, setup instructions, test
  instructions and a technical decision log covering at least the chunking strategy and the
  stack.
- Architecture decisions MUST be recorded as ADRs in `docs/adr`, written in business language
  with the technical evidence in a final annex. Documentation MUST describe the current state,
  not its change history.
- Prose MUST use semicolons only where grammatically correct and never to join unrelated
  ideas. Text after a colon is capitalized only in label or definition form.
- `AGENTS.md` at the repository root MUST be the single source of agent and contributor
  conventions, and no `CLAUDE.md` file may exist in the repository.

## Development Workflow

- Every feature MUST follow the GitHub Spec Kit flow: specify, clarify, plan, tasks, analyze,
  implement and converge.
- Commits MUST follow Conventional Commits in English with a scope and one of the types feat,
  fix, docs, refactor, test, perf, build, ci or chore. The subject is imperative, lowercase and
  under 72 characters, and breaking changes are marked with `!`.
- Branches MUST use one of the prefixes `feature/`, `fix/`, `chore/`, `docs/`, `refactor/` or
  `test/` followed by a kebab-case English slug.
- Each pull request MUST address one concern and is squash-merged. The PR title MUST equal the
  resulting commit title, and the PR body MUST contain the sections Summary, Changes, Test
  plan (with evidence), Technical decision and AI assistance.
- GitHub Actions MUST be pinned by full commit SHA, workflows MUST be audited with zizmor, and
  secrets MUST never be committed.
- All repository content MUST be written in English.

## Governance

This constitution supersedes any other practice, template default or guidance file in the
repository. Where `AGENTS.md` or a Spec Kit template disagrees with it, the constitution wins
and the conflicting file is corrected.

Amendments are proposed through a pull request that states the rationale, updates the
Sync Impact Report and bumps the version under semantic versioning. A MAJOR bump is required
for removing or redefining a principle in a backward-incompatible way, a MINOR bump for adding
a principle or section or materially expanding guidance, and a PATCH bump for clarifications
and wording fixes.

Every implementation plan MUST include a Constitution Check against Principles I to IX and the
standards above, evaluated before research and again after design. Any justified deviation
MUST be recorded in the plan's Complexity Tracking table together with the simpler
alternative that was rejected. Pull request reviews MUST verify compliance, and CI enforces
the automatable rules (import boundaries, lint, types, coverage, workflow audit).

**Version**: 1.1.0 | **Ratified**: 2026-09-28 | **Last Amended**: 2026-10-02
