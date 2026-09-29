# AGENTS.md

Conventions for AI coding agents and human contributors working on
multimodal-rag-system. This file is the single source of contributor conventions.
The project constitution in `.specify/memory/constitution.md` defines the
non-negotiable principles and takes precedence over this file when they disagree.

## Project

A multimodal RAG system that ingests technical PDFs (text, tables, diagrams and
images) and answers natural-language questions with citations to the source
document and page, together with the closest relevant image.

| Path | Content |
| --- | --- |
| `backend/` | Python API and ingestion worker |
| `frontend/` | Chat client |
| `docs/adr/` | Architecture decision records |
| `specs/` | Spec Kit feature artifacts (spec, plan, tasks) |
| `.specify/` | Spec Kit configuration, constitution, templates and scripts |
| `.claude/skills/` | Spec Kit commands exposed as agent skills |

The challenge brief lives locally at `docs/RAG Multimodal.pdf`. It is git-ignored
and MUST never be committed, quoted at length or uploaded anywhere.

## Spec-driven workflow

Every feature goes through the GitHub Spec Kit commands in this order:

1. `/speckit-specify` writes the feature specification (what and why).
2. `/speckit-clarify` resolves ambiguities in the specification.
3. `/speckit-plan` produces the technical plan, including the Constitution Check.
4. `/speckit-tasks` breaks the plan into ordered tasks.
5. `/speckit-analyze` checks consistency across spec, plan and tasks.
6. `/speckit-implement` executes the tasks.
7. `/speckit-converge` compares the code with the artifacts and appends missing work.

Template customizations go in `.specify/templates/overrides/`, which takes
precedence over the core templates and survives Spec Kit upgrades. Core templates
under `.specify/templates/` are not edited by hand.

## Commands

Run these from the repository root. The backend is a uv project in `backend/`.

| Purpose | Command |
|---|---|
| Install dependencies | `uv sync --project backend` |
| Install the git hooks once | `uv run --project backend pre-commit install` |
| Run every static check (ruff, typos, mypy, import contracts, file hygiene) | `uv run --project backend pre-commit run --all-files` |
| Run the tests with the 90% coverage gate | `uv run --directory backend pytest --cov` |
| Check the import contracts only | `uv run --directory backend lint-imports` |
| Audit the GitHub Actions workflows | `uvx zizmor --persona=pedantic .github/workflows/` |
| Start the whole system (after `cp .env.example .env`) | `docker compose up -d --build --wait` |
| Stop it, keeping data | `docker compose down` |
| Run the API or the worker outside Docker | `uv run --directory backend python -m multimodal_rag {api,worker}` |
| Create a migration after changing `tables.py` | `uv run --directory backend alembic revision --autogenerate -m "<change>"` |
| Regenerate the test PDFs | `uv run --directory backend python tests/fixtures/build_fixtures.py` |

Integration tests start PostgreSQL and Qdrant with testcontainers, so Docker must be
running. Docker Model Runner must be enabled once with
`docker desktop enable model-runner --tcp 12434 --cors none` before `docker compose up`.

CI runs the same pre-commit hooks and the same test command, so a clean local run means
a clean CI run.

## Architecture rules

The constitution holds the full list. The rules an agent is most likely to break
are these:

- The domain core and use cases import no framework, SDK, vector DB client or PDF
  library. LLM, embeddings, vector store, extractor, job store and queue are reached
  only through ports and wired in one composition root.
- PDF processing never runs inside an HTTP request. Uploads return a `job_id`, and
  job state is persisted and queryable.
- Every external call has an explicit timeout and a retry or circuit-breaker policy
  with configurable defaults.
- Errors derive from one root exception, with a specific subclass per root cause.
  Bare `except` is forbidden.

## Code conventions

- Python is managed only with uv, with a pinned interpreter, `pyproject.toml` and a
  versioned `uv.lock`.
- ruff lints and formats (line length 88), and mypy runs in strict mode with the
  pydantic plugin. pre-commit runs the same checks as CI.
- No `print` in application code. Each module uses
  `logger = logging.getLogger(__name__)` and logs with lazy `%s` formatting. Logs
  never include secrets, tokens or personal data.
- Public functions carry modern type hints, and new parameters on existing
  functions are keyword-only.
- Settings come from environment variables through pydantic-settings. Required
  settings have no default. `.env.example` is committed and `.env` never is.
- Fix defects at their root cause, reuse existing code before adding new code, and
  apply a pattern change everywhere the pattern appears.
- Group code by feature or concern. Names describe what the code is or does, never
  the ticket or bug behind it.

## Tests

- Unit tests use fakes that implement the ports (fake LLM, in-memory vector store)
  and `respx` for HTTP adapters. `MagicMock` and `Mock` are not used.
- Tests assert behavior through public interfaces.
- A bug fix includes a test that fails before the fix and passes after it.
- CI fails when backend coverage drops below 90%.

## Documentation

- Google-style docstrings (Args, Returns, Raises) on every public module, class and
  function.
- Inline comments are one line and explain what non-obvious code does and why it
  is there, without ticket references.
- Documentation describes the current state of the system, not its history. ADRs in
  `docs/adr/` are written in business language, with technical evidence in a final
  annex.
- Semicolons appear only where grammatically correct and never join unrelated
  ideas. Text after a colon is capitalized only in label or definition form.
- Everything in the repository is written in English: code, comments, docs, specs,
  commits and pull requests.
- There is no `CLAUDE.md`. Claude Code reads this file natively only when no
  `CLAUDE.md` or `CLAUDE.local.md` exists, so do not create one.

## Git and pull requests

- Branches use the prefixes `feature/`, `fix/`, `chore/`, `docs/`, `refactor/` or
  `test/` followed by a kebab-case English slug, for example
  `feature/async-pdf-ingestion`.
- Commits follow Conventional Commits with a scope, for example
  `feat(ingestion): add job status endpoint`. The subject is imperative, lowercase
  and under 72 characters, and breaking changes are marked with `!`.
- One concern per pull request, merged by squash. The PR title equals the commit
  title, and the body has the sections Summary, Changes, Test plan (with evidence),
  Technical decision and AI assistance.
- GitHub Actions are pinned by full commit SHA and audited with zizmor. Secrets are
  never committed.

## Choosing patterns

- Never reimplement logic that already exists. Before writing any helper, class or
  utility, check in this order and report the result:
  1. The project's own modules.
  2. The dependencies already installed, by reading their source in
     `backend/.venv/lib/python3.14/site-packages` or their official documentation.
  3. The Python standard library.

  New code is written only when all three come up empty, and the pull request states
  why. Retries, for example, go through `shared/resilience.py`, which wraps stamina.
- Before introducing a usage pattern (an entry point, a startup command, a settings
  layout, middleware, error handling, a project layout), check how the official
  documentation of the framework or library does it. For FastAPI that is
  fastapi.tiangolo.com, and for the server that is uvicorn.dev.
- When the documentation does not cover the case, follow a widely used reference
  codebase (for example the official full-stack-fastapi-template, Apache Airflow,
  Prefect or Polar) and name it in the pull request's Technical decision section.
- A pattern chosen from habit, with no documentation or reference behind it, is
  proposed to the maintainer before it is written.

## Agent boundaries

- Commit only when the maintainer asks for it. Never push, and never delete
  branches, including merged ones.
- Ask before implementing when a design choice is ambiguous, and present the
  evidence, the options and a recommendation.
- Never stop processes or servers the maintainer started. Check whether a port is
  in use before starting a service on it.
