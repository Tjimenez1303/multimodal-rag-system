# Implementation Plan: Reranked Relevance Gate

**Branch**: `feature/reranked-relevance-gate` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-reranked-relevance-gate/spec.md`

## Summary

The answering use case stops gating on the dense cosine similarity and asks a local
reranker, Qwen3-Reranker-0.6B, how likely each retrieved candidate is to contain the
answer. The answer model is asked only when a supplied unit reaches that judged relevance
or holds an identifier of the question, and it receives the units in judged order.

- **Candidates.** The hybrid search now returns up to 16 distinct units instead of 8. All
  16 are judged in parallel, and the 8 with the highest relevance are supplied, with the
  fused rank breaking ties. A candidate holding an identifier of the question, such as a
  part number, is always supplied, as RAGFlow keeps term similarity in its final ranking
  after a reranker.
- **Judgement.** One OpenAI-format `chat/completions` request per candidate carries the
  model card's judging prompt with a task instruction of this project, and asks for one
  token with its log probabilities. The relevance is the probability of `yes` against
  `no`. Long passages are shortened with the tokenizer the image already bakes, which the
  reranker shares with the embedding model.
- **Gate.** `MIN_RELEVANCE` (0.30) replaces `MIN_SIMILARITY` (0.60). The identifier rule
  stays and is evaluated over the supplied units. The dense similarity remains in each
  source as information.
- **Failures.** The reranker has its own timeout and the shared retry policy, and its time
  counts toward the question's deadline. When it stays down, the question fails with
  `reranker_unavailable`, `reranker_timeout` or `reranker_invalid_response`, and nothing
  falls back to the old gate.
- **Serving.** Docker Model Runner serves the reranker in completion mode, declared in the
  Compose `models` element and bound to the API only.

The spec calls the reranker "the ranking model", its business name. Code, settings and
error codes use `reranker`, the name in the model card and the Compose file.

On 31 labeled questions, the judged gate let through 15 of 18 answerable questions, 0 of
9 hard negatives and 0 of 4 unrelated ones, against 8, 5 and 0 for the similarity gate,
and judging took 58 to 581 ms. Decisions, alternatives, sources and measurements are in
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.14 (pinned patch in `.python-version`), managed with uv

**Primary Dependencies**: all already installed.

- httpx and stamina, through `post_json` and `call_with_retry`.
- tokenizers, through `HuggingFaceTokenCounter`, now loaded by the API as well.
- The frontend gains no dependency. Its typed client is regenerated for the new field.

**Storage**: none. Judgements exist only for the duration of a question.

**Testing**:

- pytest with a `FakeRelevanceJudge` for the use case.
- respx for the reranker adapter.
- Contract tests of `askQuestion` against this feature's contract.
- A labeled question set and an evaluation script run against the live system, like the
  backlog load script, with their scoring functions unit-tested.

**Target Platform**: Linux containers through Docker Compose on the reference machine of
feature 001, an Apple M4 Pro, with the models on the host GPU through Docker Model Runner.

**Project Type**: web service. The change is inside the existing answering use case and
its `POST /api/v1/questions` route.

**Performance Goals**:

| Criterion | Target | Measured basis |
|---|---|---|
| SC-004 | Judging adds under 2.5 s to 95% of questions | 1.4 s median and 2.5 s at the 95th percentile for 16 candidates of the sample manuals (research section 12) |
| SC-001 | Answerable 90% | 36 of 36 in the labeled evaluation |
| SC-002 | Short answerable 75% | 18 of 18 in the labeled evaluation |
| SC-003 | Unanswerable stopped 70%, not enough information 90% | 15 of 22 (68%) and 21 of 22 (95%), see below |
| SC-005 | Specific error within the deadline, library under 2 s | The same failure path as search and the answer model |
| SC-007 | Identifier units supplied for 95% of identifier questions | 9 of 9 in the labeled evaluation |

The first part of SC-003 misses its target by one question. That question passed because
the identifier rule of the question answering feature counts the year "2019" as a code,
which is recorded as its own follow-up. The other questions that passed are near misses
the answer model then declined, and raising `MIN_RELEVANCE` above them would also reject
answerable questions (research section 12). The maintainer accepted the result on
2026-09-29.

**Constraints**:

- Everything runs locally, and questions and documents never leave the machine (FR-010).
- The core imports no framework, SDK or provider, and never sees the reranker's prompt.
- One judging request holds at most `RERANKER_MAX_INPUT_TOKENS` (2,048), one slot of the
  reranker's 8,192-token context.
- About 1.2 GB of additional model memory on the host.

**Scale/Scope**: 16 judging requests per question, at most 2 questions answered at once,
so at most 32 concurrent requests, which the reranker's slots queue.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Hexagonal architecture | The gate, ordering and failure mapping stay in `answering/`, which imports no adapter. The prompt, the instruction and the token budget live in the adapter. The existing import-linter contracts cover the new modules without change | Pass |
| II. Ports and adapters | New port `RelevanceJudge` in `answering/ports.py`, with the production adapter `adapters/openai_compatible/reranker.py` and `FakeRelevanceJudge`. The adapter reuses the `TokenCounter` port. Wiring happens only in `bootstrap.py`, and another reranker needs only a new adapter or a new URL | Pass |
| III. Asynchronous ingestion | Unchanged | Pass |
| IV. Multimodal fidelity | Unchanged. Judging reads the unit's text with its heading path, and image selection is untouched | Pass |
| V. Grounded answers | Hybrid retrieval is unchanged, and reranking orders its results. The gate still stops the model when nothing relevant was retrieved, and the model's abstention stays. Unit tests cover the not-enough-information outcome of the new gate | Pass |
| VI. Resilience | The reranker has an explicit timeout, retries through `call_with_retry` with backoff and jitter, three specific errors mapped in the one HTTP table, and no provider payload in responses. Its time counts toward the total deadline | Pass |
| VII. Observability | The per-question log line gains `ranking_ms` and `top_relevance`, with no question, answer or content. Retries are logged by the shared policy | Pass |
| VIII. Test discipline | The fake implements the port, the adapter is tested with respx, no `MagicMock`. Behavior is asserted through the use case, the adapter and the route. The bug fix gets a failing test first: the "Total Neto" case through the use case with the fake judge | Pass |
| IX. Configuration and delivery | New settings through pydantic-settings, documented in `.env.example`. `RERANKER_URL` and `RERANKER_MODEL` are required with no default and are injected by Compose. `docker compose up` still starts everything, the reranker included | Pass |
| Engineering standards | uv, ruff, mypy strict, pre-commit. No new dependency. New parameters are keyword-only | Pass |
| Documentation standards | Google-style docstrings. ADR 0009 records the reranked gate in business language with the measurements in its annex, and ADR 0005 points to it for the gate. The README updates the question flow, the diagram and the settings | Pass |
| Development workflow | Spec Kit flow, Conventional Commits, `feature/` branch, squash merge | Pass |

**Post-design re-check (after Phase 1)**: all gates still pass. The design adds one port,
one adapter, three errors and seven settings, reuses the transport, retry policy,
tokenizer and error mapping, and adds no dependency. There is no deviation to track.

## Project Structure

### Documentation (this feature)

```text
specs/004-reranked-relevance-gate/
├── plan.md              # This file
├── research.md          # Phase 0: decisions, alternatives, sources, measurements
├── data-model.md        # Phase 1: judged hits, source relevance, port, errors
├── quickstart.md        # Phase 1: end-to-end validation guide
├── contracts/
│   └── openapi.yaml     # Phase 1: askQuestion with source relevance and reranker errors
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── src/multimodal_rag/
│   ├── shared/config.py                  # reranker settings, MIN_RELEVANCE, tokenizer path shared
│   ├── answering/
│   │   ├── domain.py                     # + JudgedHit, RetrievedSource.relevance
│   │   ├── ports.py                      # + RelevanceJudge
│   │   ├── errors.py                     # + RerankerUnavailable, Timeout, Response errors
│   │   ├── relevance.py                  # gate on judged relevance, judged ordering
│   │   ├── sources.py                    # relevance and judged rank on each source
│   │   └── use_cases/ask.py              # candidates, judging, selection, timings, mapping
│   ├── adapters/
│   │   ├── openai_compatible/
│   │   │   ├── reranker.py               # RelevanceJudge over chat/completions logprobs
│   │   │   └── chat.py                   # ChatCompletion reads the first token's logprobs
│   │   └── http/
│   │       ├── schemas.py                # + relevance on the source body
│   │       └── problems.py               # + reranker errors
│   └── bootstrap.py                      # reranker client, token counter, adapter wiring
└── tests/
    ├── fakes.py                          # + FakeRelevanceJudge
    ├── fixtures/build_fixtures.py        # + labeled_total.pdf
    ├── unit/answering/                   # gate, ordering, sources, use case
    ├── unit/adapters/                    # reranker adapter with respx
    ├── contract/contract.py              # + this feature's contract
    └── evaluation/                       # relevance_questions.yaml, evaluate_relevance.py

frontend/
├── openapi.json                          # regenerated from the API
└── src/client/                           # regenerated typed client

compose.yaml                              # models: reranker, bound to the api service
.env.example                              # reranker settings and MIN_RELEVANCE
docs/adr/0009-reranked-relevance-gate.md
docs/adr/0005-grounded-answers-and-relevance-gate.md   # gate section points to ADR 0009
docs/images/architecture.drawio.svg       # reranker next to the answer model
README.md                                 # question flow, settings, design decisions
```

**Structure Decision**: the layout of features 001 and 002 is kept. The reranker is a
provider of the answering core like the answer model, so its port sits in
`answering/ports.py` and its adapter next to the other OpenAI-compatible adapters. The
contract of this feature redefines `askQuestion` by extending the question answering
contract's schemas, so the earlier contract keeps describing its own feature.

## Complexity Tracking

No constitution deviation. The notable choices, each explained in research.md, are:

- Scoring through `chat/completions` log probabilities instead of the `/rerank` endpoint,
  because the endpoint cannot take this project's instruction (sections 4 and 5).
- Judging 16 candidates to supply 8 (section 7).
- Failing the question when the reranker is down, with no fallback (section 8).
