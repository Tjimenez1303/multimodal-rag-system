---

description: "Task list for the reranked relevance gate"
---

# Tasks: Reranked Relevance Gate

**Input**: Design documents from `specs/004-reranked-relevance-gate/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/openapi.yaml](contracts/openapi.yaml),
[quickstart.md](quickstart.md)

**Tests**: Test tasks are REQUIRED for every user story (constitution Principle VIII).

- Unit tests use the fakes in `backend/tests/fakes.py`, which implement the ports, and
  `respx` for HTTP adapters. Never use `MagicMock` or `Mock`.
- Backend coverage MUST stay at or above 90%.
- Write each story's tests first and confirm they fail before implementing. This feature
  fixes a defect, so the "Total Neto" test of T013 MUST fail on the current gate.

**Organization**: tasks are grouped by user story, so each story can be implemented,
tested and demonstrated on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task belongs to (US1 to US4)
- Every description names the exact file

## Path Conventions

- Backend code lives in `backend/src/multimodal_rag/`, tests in `backend/tests/`.
- The answering core is `backend/src/multimodal_rag/answering/` and imports only the
  ingestion domain and ports, `shared` and the standard library.
- Run commands from the repository root, as listed in `AGENTS.md`.

---

## Phase 1: Setup

**Purpose**: provision the reranker and the fixture the stories are demonstrated with

- [X] T001 Declare the reranker in `compose.yaml` (research section 9):
  - **Model.** Add `reranker` to the top-level `models` element with `model: ai/qwen3-reranker:0.6B` and `context_size: 8192`, and no runtime flags, so Docker Model Runner serves it in completion mode.
  - **Binding.** Bind it to the `api` service only, with `endpoint_var: RERANKER_URL` and `model_var: RERANKER_MODEL`, next to `vlm` and `embedder`. Extend the comment above the `api` models to say the reranker is only called when a question arrives.
  - **Check.** `docker compose config` succeeds.
- [X] T002 [P] Document the new settings in `.env.example`, in the style of the existing entries:
  - The header comment lists `ai/qwen3-reranker:0.6B` among the pulled models, updates the total download size, and lists `RERANKER_URL` and `RERANKER_MODEL` among the values injected into the API.
  - The commented defaults list `RERANKER_TIMEOUT_SECONDS=15`, `RERANKER_INSTRUCTION`, `RERANKER_MAX_INPUT_TOKENS=2048`, `RERANK_CANDIDATES=16` and `MIN_RELEVANCE=0.30`, and `MIN_SIMILARITY` is removed.
  - `EMBEDDER_TOKENIZER_PATH` is described as used by the API and the worker.
- [X] T003 [P] Add a `labeled_total.pdf` fixture to `backend/tests/fixtures/build_fixtures.py`: a two-page maintenance quote in Spanish with invented names and amounts, a table of items on page 1 and, on page 2 only, a grey box titled "Terminos y Condiciones" and the line "Total Neto: $880,900.0", the sum of the items. Regenerate the fixtures with `uv run --directory backend python tests/fixtures/build_fixtures.py`.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: settings, domain, port, fake, chat model and contract loading that every story needs

**⚠️ CRITICAL**: no user story work can begin until this phase is complete

- [X] T004 Change the settings in `backend/src/multimodal_rag/shared/config.py` (research section 9):
  - **Shared.** Move `embedder_tokenizer_path: Path` from `WorkerSettings` to `ProviderSettings`, with its docstring saying the API uses it to shorten reranker passages.
  - **`ApiSettings` additions.** `reranker_url: HttpUrl` (required), `reranker_model: str` (required, `min_length=1`), `reranker_timeout_seconds: PositiveFloat = 15.0`, `reranker_instruction: str` (`min_length=1`, default "Given a question about a document, judge whether the passage contains the information that answers it"), `reranker_max_input_tokens: PositiveInt = 2048`, `rerank_candidates: PositiveInt = 16`, `min_relevance: float = Field(default=0.30, ge=0, le=1)`.
  - **Removal.** Delete `min_similarity` and its docstring entry.
  - **Validators.** Extend the `ApiSettings` validator with "RERANK_CANDIDATES must be at least RETRIEVAL_TOP_K" and "RERANKER_TIMEOUT_SECONDS must be shorter than ANSWER_DEADLINE_SECONDS".
  - **Tests.** Update `backend/tests/unit/shared/test_config.py`: the new defaults, the two required reranker settings, both validators, and that `MIN_SIMILARITY` is no longer read.
- [X] T005 [P] Add the reranker errors to `backend/src/multimodal_rag/answering/errors.py`, after the answer model errors, with fixed messages that name the reranker and no provider data (data-model.md, Errors):
  - `RerankerUnavailableError(ProviderUnavailableError)`, code `reranker_unavailable`, "The reranker is unavailable."
  - `RerankerTimeoutError(ProviderTimeoutError)`, code `reranker_timeout`, "The reranker did not answer in time."
  - `RerankerResponseError(ProviderResponseError)`, code `reranker_invalid_response`, "The reranker returned a judgement that cannot be used."
- [X] T006 [P] Extend the answering domain in `backend/src/multimodal_rag/answering/domain.py` as data-model.md defines:
  - **`JudgedHit`.** A frozen, slotted dataclass with `hit: SearchHit` and `relevance: float`, the "probability that the unit contains the answer", validated to lie "in 0 to 1".
  - **`RetrievedSource.relevance: float`.** Documented as the unit's judged relevance, and `rank` documented as the "position in judged order". `similarity` is documented as informational.
  - **Tests.** Extend `backend/tests/unit/answering/test_domain.py` for the 0 to 1 bounds of `JudgedHit.relevance`.
- [X] T007 Define the `RelevanceJudge` port in `backend/src/multimodal_rag/answering/ports.py`: `async def judge(self, question: str, passages: Sequence[str]) -> list[float]`, "one relevance per passage in the same order", with a Google-style docstring that lists the `ProviderUnavailableError`, `ProviderTimeoutError` and `ProviderResponseError` it raises. Update the module docstring.
- [X] T008 Add `FakeRelevanceJudge` to `backend/tests/fakes.py` and wire it into `backend/tests/library.py`:
  - **Fake.** Relevance per passage text through a mapping, a configurable default (1.0), scripted errors consumed one per call, an optional delay, and a record of every `(question, passages)` call.
  - **Library.** `library.judge` holds the fake, `library.ask()` passes it as `judge=`, and its default options replace `min_similarity` with `min_relevance: 0.30` and add `rerank_candidates: 16`.
  - **Protocol check.** Extend `backend/tests/unit/test_fakes_match_ports.py` with the new port and raise the expected count to 15.
- [X] T009 [P] Read log probabilities in `backend/src/multimodal_rag/adapters/openai_compatible/chat.py`:
  - **Model.** Add an optional `logprobs` to `_Choice`, holding `content`, a list of generated tokens, each with `token`, `logprob` and `top_logprobs` (a list of `token` and `logprob`). Unknown fields stay ignored.
  - **Property.** `ChatCompletion.first_token_logprobs -> dict[str, float] | None` maps each candidate token of the first generated token to its log probability, and is `None` when the answer has no log probabilities.
  - **Tests.** Add cases to `backend/tests/unit/adapters/test_openai_compatible.py`: a body with log probabilities, a body without them, and the existing answers still parsing.
- [X] T010 [P] Register `specs/004-reranked-relevance-gate/contracts/openapi.yaml` in `CONTRACT_FILES` of `backend/tests/contract/contract.py`, after the 003 contract, so its `askQuestion` replaces the 002 definition in `PATHS`. Confirm `backend/tests/contract/test_openapi_matches_contract.py` still passes.

**Checkpoint**: settings load, the port and fake match, and the chat model reads log probabilities.

---

## Phase 3: User Story 1 - Get an answer to a short or keyword-style question (Priority: P1) 🎯 MVP

**Goal**: the gate reads the reranker's judgement, so a short question whose answer is in
a retrieved unit reaches the answer model whatever its dense similarity.

**Independent Test**: quickstart Scenario 1: "Total Neto" and "Cual es mi total Neto"
over `labeled_total.pdf` return an answer that cites page 2.

### Tests for User Story 1 (REQUIRED) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T011 [P] [US1] Rewrite the gate cases of `backend/tests/unit/answering/test_relevance.py` over `JudgedHit`s:
  - A unit at exactly `min_relevance` passes, and one just below fails.
  - A unit with similarity 0.95 and relevance 0.10 fails, because the similarity no longer gates (FR-006).
  - A unit with similarity 0.20 and relevance 0.90 passes.
  - The identifier cases keep passing over the supplied units (research section 6).
  - No judged hits never passes.
- [X] T012 [P] [US1] Write `backend/tests/unit/adapters/test_openai_reranker.py` with respx:
  - **Request.** One `chat/completions` request per passage with `model`, `max_tokens` 1, `temperature` 0, `logprobs` true, `top_logprobs` 20, `chat_template_kwargs` `{"enable_thinking": false}`, the model card's system sentence verbatim (research section 4), and the user message `<Instruct>: {instruction}\n<Query>: {question}\n<Document>: {passage}`.
  - **Score.** `yes` −0.1 and `no` −2.4 give `exp(-0.1) / (exp(-0.1) + exp(-2.4))`. Only `yes` in the top gives 1.0, only `no` gives 0.0.
  - **Invalid answers.** Neither token, or no log probabilities, raises `ProviderResponseError`.
  - **Order.** Scores come back in passage order when the responses arrive out of order.
  - **Length.** A passage longer than the budget is shortened with the injected `WordTokenCounter` so the whole prompt fits `max_input_tokens`, keeping its first words, and a passage that fits is sent unchanged.
  - **Edge and retries.** No passages returns `[]` without any request. A 503 followed by a success is retried through the policy.
- [X] T013 [P] [US1] Add the short-question cases to `backend/tests/unit/answering/test_ask.py`:
  - **Regression.** A unit on page 2 with text "Terminos y Condiciones\nTotal Neto:\n$880,900.0", fake similarity 0.43 and judged relevance 0.99, asked "Total Neto", returns `answered` citing page 2. This test MUST fail before T016.
  - **Candidates.** The judge receives each candidate's `embedding_text`, up to `rerank_candidates` distinct candidates, and the question text. A question restricted to one document sends the judge only that document's units (spec edge cases).
  - **Selection.** With 16 candidates, the 8 with the highest relevance are supplied to the answer model.
  - **Identifier kept.** For "What is code SPL-480?", the unit holding `SPL-480` judged ninth of 16 (relevance 0.05, below `min_relevance`) is supplied, replacing the lowest judged unit, and the question is `answered` citing it (FR-007, SC-007).
  - **Migration.** Migrate every existing case of this file that sets `min_similarity` or relies on low similarity for a not-enough-information outcome to `min_relevance` and judged relevance.

### Implementation for User Story 1

- [X] T014 [US1] Rewrite the gate in `backend/src/multimodal_rag/answering/relevance.py` (research sections 6 and 7):
  - `rank_by_relevance(hits: Sequence[SearchHit], relevances: Sequence[float], *, limit: int, question: str) -> list[JudgedHit]` keeps the first `limit` by descending relevance with a stable sort over the search order, so the fused rank breaks ties. Every hit that holds one of `question_identifiers(question)` as a whole token is kept too, "each one replacing the lowest judged kept unit that holds none", and "when more than `RETRIEVAL_TOP_K` hold one, those with the highest relevance are kept" (data-model.md). The kept hits are returned in judged order.
  - Update the module docstring with why identifier units are kept, citing RAGFlow's `rerank_by_model` term-similarity blend (research section 7).
  - `passes_gate(judged: Sequence[JudgedHit], *, min_relevance: float, question: str) -> bool` passes when a judged hit reaches `min_relevance` or holds an identifier of the question as a whole token.
  - Update the module docstring: the dense similarity no longer gates, and why (research section 2).
- [X] T015 [P] [US1] Implement `OpenAICompatibleRelevanceJudge` in `backend/src/multimodal_rag/adapters/openai_compatible/reranker.py` (research sections 4, 5 and 7):
  - **Constructor.** `client`, and keyword-only `model`, `instruction`, `tokens: TokenCounter`, `max_input_tokens` and `retry`.
  - **Prompt.** The system sentence and user message of T012. The passage budget is `max_input_tokens` minus the token count of the prompt with an empty document, and each passage is shortened with `TokenCounter.truncate`.
  - **Calls.** One `post_json(..., answer=ChatCompletion, service="reranker")` per passage inside an `asyncio.TaskGroup`, so the first failure or a cancellation stops the rest.
  - **Score.** Computed from `first_token_logprobs` as research section 4 defines, raising `ProviderResponseError` when both tokens or the log probabilities are missing.
  - **Docs.** A module docstring that names the model card's method and why the `/rerank` endpoint is not used.
- [X] T016 [US1] Judge and select in `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py`:
  - **Options.** `AnsweringOptions` replaces `min_similarity` with `min_relevance`, adds `rerank_candidates`, and the constructor takes `judge: RelevanceJudge`.
  - **Search.** `_search` asks for `rerank_candidates * SEARCH_OVERFETCH` hits and keeps `distinct_hits(..., limit=rerank_candidates)`.
  - **Judging.** A new step calls `judge.judge(question.text, [hit.unit.embedding_text for hit in hits])`, then `rank_by_relevance(..., limit=top_k, question=question.text)`, then `passes_gate` on the result. The rest of the flow receives the judged hits in judged order.
  - **Timings.** `_Timings` gains `ranking_ms`. The per-question log line gains `ranking_ms %.1f` and `top_relevance %.3f` (FR-014).
  - **Docs.** Update the module and class docstrings.
- [X] T017 [US1] Wire the reranker in `backend/src/multimodal_rag/bootstrap.py`:
  - **Client.** `_answering_state` opens an `httpx.AsyncClient` with `base_url=str(settings.reranker_url)` and `timeout=settings.reranker_timeout_seconds` on the same exit stack.
  - **Adapter.** It builds `HuggingFaceTokenCounter.from_file(settings.embedder_tokenizer_path)` and passes `OpenAICompatibleRelevanceJudge` as `judge=`, with the new options.
  - **Tests.** Extend `backend/tests/unit/test_bootstrap.py` for the API's new required settings.

**Checkpoint**: short questions answered and identifier units still supplied, quickstart Scenarios 1 and 5 pass on the running system.

---

## Phase 4: User Story 2 - Stop questions the documents cannot answer before the answer model (Priority: P1)

**Goal**: questions on the documents' topic that they do not answer, and unrelated
questions, end as not enough information without an answer model call.

**Independent Test**: quickstart Scenario 3: the questions return `no_relevant_content`
in under 2 seconds, with no sources.

### Tests for User Story 2 (REQUIRED) ⚠️

- [X] T018 [P] [US2] Add the rejection cases to `backend/tests/unit/answering/test_ask.py`:
  - Every candidate judged below `min_relevance`, with high similarities, returns `not_enough_information` with reason `no_relevant_content`, no sources, citations or images, and `FakeAnswerGenerator` received no prompt.
  - The same holds for an unrelated question whose candidates are all judged near 0.
  - A question the judge lets through, whose model reply is empty, still ends as `not_answered_by_sources` (US2 scenario 3).
- [X] T019 [P] [US2] Add a case to `backend/tests/unit/adapters/test_openai_reranker.py`: a custom `instruction` given to the constructor appears verbatim after `<Instruct>: ` in every request, so `RERANKER_INSTRUCTION` reaches the model (FR-002).

### Implementation for User Story 2

- [X] T020 [US2] Make `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py` log `top_relevance` also for questions stopped by the gate, where it is the highest judgement of all candidates, since those values tune `MIN_RELEVANCE` (research section 10). Assert it with `caplog` in `backend/tests/unit/answering/test_ask.py`, and assert that the question text is not in the record.

**Checkpoint**: US1 and US2 together give the corrected gate in both directions.

---

## Phase 5: User Story 3 - Give the answer model the best passages first (Priority: P2)

**Goal**: sources are supplied and returned in judged order, each with its relevance.

**Independent Test**: quickstart Scenario 4: `rank` increases while `relevance` never
increases, and every source carries a relevance in 0 to 1.

### Tests for User Story 3 (REQUIRED) ⚠️

- [X] T021 [P] [US3] Add ordering cases to `backend/tests/unit/answering/test_relevance.py`: descending relevance, the search order breaking a tie, `limit` applied after sorting, an identifier hit outside the top `limit` replacing the lowest judged hit that holds no identifier, and more identifier hits than `limit` keeping the highest judged ones.
- [X] T022 [P] [US3] Extend `backend/tests/unit/answering/test_sources.py`: each source carries its `relevance`, and `rank` is its 1-based position in judged order.
- [X] T023 [P] [US3] Add a case to `backend/tests/unit/answering/test_ask.py`: the answer model's prompt numbers the sources in judged order, and the response lists them in that order.
- [X] T024 [P] [US3] Extend `backend/tests/contract/test_questions_contract.py` so every answer case is validated against the 004 contract, where each source "requires `relevance`", a number with "minimum: 0" and "maximum: 1".

### Implementation for User Story 3

- [X] T025 [US3] Make `assemble_sources` in `backend/src/multimodal_rag/answering/sources.py` take `Sequence[JudgedHit]` and set `relevance` and the judged `rank` on each `RetrievedSource`. Update its caller in `backend/src/multimodal_rag/answering/use_cases/ask.py`.
- [X] T026 [US3] Add `relevance: float` to the source body in `backend/src/multimodal_rag/adapters/http/schemas.py`, with `Field(ge=0, le=1)` and the contract's description, and update the descriptions of `rank` and `similarity` to match the 004 contract.
- [X] T027 [US3] Regenerate the typed client and update the client's answer fixtures:
  - **Client.** Run `uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json && npm --prefix frontend run generate-client`. `frontend/openapi-ts.config.ts` sets `validator: { response: "zod" }` on the `@hey-api/sdk` plugin, so `askQuestion` parses every answer with `zAskQuestionResponse` and a source without `relevance` becomes a validation error.
  - **Fixtures.** Add a `relevance` between 0 and 1, non-increasing with `rank`, to every source in `frontend/tests/fixtures/answers/*.json`, `frontend/tests/fixtures/answers/sample.ts` and `frontend/tests/msw/handlers.ts`.
  - **Checks.** Run `npm --prefix frontend run typecheck`, `npm --prefix frontend run test:coverage` and `npm --prefix frontend run test:e2e`.

**Checkpoint**: sources carry their judgement, and the client types include it.

---

## Phase 6: User Story 4 - Get a clear outcome when the ranking model is slow or down (Priority: P2)

**Goal**: reranker failures end the question with a specific error within the deadline,
with no fallback, while uploads and status checks keep working.

**Independent Test**: quickstart Scenario 6: 503 `reranker_unavailable` within the
deadline, and the library answers in under 2 seconds.

### Tests for User Story 4 (REQUIRED) ⚠️

- [X] T028 [P] [US4] Add failure cases to `backend/tests/unit/answering/test_ask.py`:
  - The fake judge raising `ProviderUnavailableError`, `ProviderTimeoutError` or `ProviderResponseError` makes the question raise `RerankerUnavailableError`, `RerankerTimeoutError` or `RerankerResponseError`, and the answer model receives no prompt.
  - A judge delay longer than `deadline_seconds` raises `AnswerDeadlineExceededError`.
  - Cancelling the question while the judge waits cancels it and frees its place in `FakeAnswerSlots` (FR-015).
- [X] T029 [P] [US4] Extend `backend/tests/unit/adapters/test_http_app.py`: `reranker_unavailable` maps to 503, `reranker_timeout` to 504 and `reranker_invalid_response` to 502, each with its fixed detail and no provider data.
- [X] T030 [P] [US4] Add a case to `backend/tests/unit/adapters/test_openai_reranker.py`: when one passage's request fails for good, the error propagates and the other pending requests are cancelled.

### Implementation for User Story 4

- [X] T031 [US4] Name reranker failures in `backend/src/multimodal_rag/answering/use_cases/ask.py`: add a `_RERANKER_FAILURES` mapping from the three provider families to the three reranker errors, and wrap the judging step in `_named(_RERANKER_FAILURES)`, as search and generation are.
- [X] T032 [US4] Map the three errors in `backend/src/multimodal_rag/adapters/http/problems.py`: 503, 504 and 502 in the status table, and in the list of errors whose fixed message is sent as the problem detail.

**Checkpoint**: all four stories work, and every reranker failure is named.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: evaluation, documentation and final validation

- [X] T033 [P] Write `backend/tests/evaluation/relevance_questions.yaml` (research section 11):
  - **Content.** Questions over the two digital sample manuals and `labeled_total.pdf` (research section 11), reaching "at least 10 answerable questions of one to three words", "at least 10 questions on the topic of a sample document whose answer it does not contain", "at least 3 answerable questions in Spanish about an English document and 3 in English about a Spanish document" (FR-003) and the identifier questions of the sample manuals (SC-007).
  - **Fields.** Each entry holds `id`, `question`, `language`, `label` (`answerable`, `hard_negative` or `unrelated`), for answerable entries `expected_document`, and for identifier questions `identifier` and `expected_pages`.
- [X] T034 Write `backend/tests/evaluation/evaluate_relevance.py`:
  - **Run.** It posts every question to `--api` and computes SC-001 (answerable reaching the model), SC-002 (short answerable reaching it), SC-003 (unanswerable stopped by the gate, and ending as not enough information overall) SC-007 (identifier questions with a supplied source from their `expected_document` on one of their `expected_pages`) and SC-004 (95th percentile of the request time of the questions stopped by the gate, which pay only search and judging, so it bounds the judging time from above; measured after one warm-up question so no model load is counted).
  - **Report.** It prints the top relevance per label, which tunes `MIN_RELEVANCE`, and exits non-zero when a criterion misses its target.
  - **Tests.** Unit-test its pure scoring functions in `backend/tests/evaluation/test_evaluate_relevance.py`, as `tests/load/` does for the backlog script.
- [X] T035 Run `evaluate_relevance.py` against the running system with the sample manuals and `labeled_total.pdf` ingested, with the default `RERANK_CANDIDATES=16`, since the 0.30 threshold was measured with 8 candidates (research section 6). If SC-001 misses its 90% target, report it to the maintainer before release instead of lowering the target (plan, Performance Goals). Tune `MIN_RELEVANCE` in `backend/src/multimodal_rag/shared/config.py` and `.env.example` if the distribution shows a better cut, and record the results and the chosen value in `specs/004-reranked-relevance-gate/research.md` section 12.
- [X] T036 [P] Write `docs/adr/0009-reranked-relevance-gate.md` in the style of ADRs 0001 to 0008, in business language, with the measurements of research sections 5, 6 and 12 in the technical annex. In `docs/adr/0005-grounded-answers-and-relevance-gate.md`, state in the gate section that ADR 0009 replaces the similarity threshold, keeping the rest of the record.
- [X] T037 [P] Update `docs/images/architecture.drawio.svg` with the reranker between search and the answer model, as an editable `.drawio.svg` with official icons and capitalized labels.
- [X] T038 [P] Update `README.md`:
  - The question flow mentions the reranker, and the model list and download size include it.
  - The settings table replaces `MIN_SIMILARITY` with `MIN_RELEVANCE` and adds the reranker settings.
  - The decision log adds ADR 0009, and the evaluation command is documented.
- [X] T039 Run `uv run --project backend pre-commit run --all-files`, `uv run --directory backend pytest --cov` and `uv run --directory backend lint-imports`, and keep coverage at or above 90%, adding unit tests in `backend/tests/unit/` where needed.
- [X] T040 Run every scenario of `specs/004-reranked-relevance-gate/quickstart.md` against `docker compose up -d --build --wait` and fix any deviation, including the first pull of the reranker on a fresh Docker Model Runner.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T001 is needed only for the running system.
- **Foundational (Phase 2)**: depends on Setup and blocks every story. T004 precedes T017.
  T006 and T007 precede T008.
- **User stories (Phases 3 to 6)**: depend on Foundational. US1 builds the judging step,
  so US2 to US4 extend `ask.py` after T016.
- **Polish (Phase 7)**: T033 to T035 need the running system with US1 to US3 done. T039
  and T040 come last.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on other stories.
- **US2 (P1)**: after US1's judging step (T016).
- **US3 (P2)**: after US1's ordering (T014 and T016). Independent of US2.
- **US4 (P2)**: after US1's judging step (T016). Independent of US2 and US3.

### Within Each User Story

- Tests are written first and fail before implementation.
- Pure core modules come before the use case, and the use case before wiring.
- `ask.py`, `test_ask.py`, `schemas.py` and `bootstrap.py` are shared, so tasks that
  touch them run in sequence.

### Parallel Opportunities

- **Setup.** T002 and T003 touch different files.
- **Foundational.** T005, T006, T009 and T010 touch different files.
- **Within US1.** T011, T012 and T013 run in parallel, and so does the adapter T015 with
  the gate T014.
- **Across stories.** After US1, the tests of US3 and US4 can be written in parallel apart
  from `test_ask.py`.
- **Polish.** T033, T036, T037 and T038 are independent.

---

## Parallel Example: User Story 1

```bash
# Tests for User Story 1 together:
Task: "Rewrite the gate cases of backend/tests/unit/answering/test_relevance.py"
Task: "Write backend/tests/unit/adapters/test_openai_reranker.py"
Task: "Add the short-question cases to backend/tests/unit/answering/test_ask.py"

# Implementation for User Story 1 together:
Task: "Rewrite the gate in backend/src/multimodal_rag/answering/relevance.py"
Task: "Implement backend/src/multimodal_rag/adapters/openai_compatible/reranker.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Complete Phases 1 and 2.
2. Complete US1 and validate quickstart Scenario 1. This is the reported defect.
3. Complete US2 right after it. Both are P1, and a gate that only opens wider would let
   hard negatives through.
4. **Stop and validate** with quickstart Scenarios 1 and 3.

### Incremental Delivery

1. US1 and US2 give the corrected gate in both directions.
2. US3 exposes the judgement on each source and orders the prompt by it.
3. US4 names reranker failures.
4. Polish measures the success criteria, tunes `MIN_RELEVANCE` and documents the decision.

---

## Notes

- [P] tasks touch different files and have no dependency on unfinished tasks.
- Commit after each task or logical group, following Conventional Commits with the
  `answering` scope, the package the change lives in, for example
  `feat(answering): gate answers on a reranker's judgement`.
- Stop at any checkpoint to validate a story on its own.
- Never log the question, the answer or document content.
