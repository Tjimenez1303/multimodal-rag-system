---

description: "Task list for grounded question answering"
---

# Tasks: Grounded Question Answering

**Input**: Design documents from `specs/002-grounded-question-answering/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/openapi.yaml](contracts/openapi.yaml),
[quickstart.md](quickstart.md)

**Tests**: Test tasks are REQUIRED for every user story (constitution Principle VIII).

- Unit tests use the fakes in `backend/tests/fakes.py`, which implement the ports, and
  `respx` for HTTP adapters. Never use `MagicMock` or `Mock`.
- Backend coverage MUST stay at or above 90%.
- Write each story's tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story, so each story can be implemented,
tested and demonstrated on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task belongs to (US1 to US6)
- Every description names the exact file

## Path Conventions

- Backend code lives in `backend/src/multimodal_rag/`, tests in `backend/tests/`.
- The answering core is `backend/src/multimodal_rag/answering/` and imports only the
  ingestion domain and ports, `shared` and the standard library.
- Run commands from the repository root, as listed in `AGENTS.md`.

---

## Phase 1: Setup

**Purpose**: dependency, package skeleton and import boundaries

- [x] T001 Add `py3langid` (BSD-3, research section 9) as a runtime dependency with `uv add --project backend py3langid`, updating `backend/pyproject.toml` and `backend/uv.lock`.
- [x] T002 Create the package skeleton with Google-style module docstrings:
  - `backend/src/multimodal_rag/answering/__init__.py` and `backend/src/multimodal_rag/answering/use_cases/__init__.py`
  - `backend/src/multimodal_rag/adapters/concurrency/__init__.py` and `backend/src/multimodal_rag/adapters/language/__init__.py`
  - `backend/tests/unit/answering/__init__.py` and `backend/tests/evaluation/__init__.py`
- [x] T003 Update the import-linter contracts in `backend/pyproject.toml`:
  - Add a `forbidden` contract for `multimodal_rag.answering` with the same forbidden modules as the ingestion contract, plus `anyio` and `py3langid`.
  - Change the `layers` contract to `(multimodal_rag.bootstrap)`, `multimodal_rag.adapters`, `multimodal_rag.answering`, `multimodal_rag.ingestion`, `multimodal_rag.shared`.
  - Confirm `uv run --directory backend lint-imports` passes.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: settings, errors, domain, ports and the adapter changes every story needs

**⚠️ CRITICAL**: no user story work can begin until this phase is complete

- [x] T004 [P] Add the `CapacityError(MultimodalRagError)` family with code `capacity_exceeded` to `backend/src/multimodal_rag/shared/errors.py`, documented as "work the system refuses because it is saturated". Extend `backend/tests/unit/shared/test_errors.py` to cover its code and that it is not a `ProviderError`, so the retry policy never repeats it.
- [x] T005 Refactor the settings in `backend/src/multimodal_rag/shared/config.py` (research section 12):
  - **`ProviderSettings(CommonSettings)`.** Move `QDRANT_*`, `EMBEDDER_URL`, `EMBEDDER_MODEL`, `EMBEDDER_TIMEOUT_SECONDS`, `EMBEDDER_DIMENSIONS` and `PROVIDER_RETRY_*` there from `WorkerSettings`. Add `EMBEDDER_QUERY_INSTRUCTION`, default `Given a question about a technical manual, retrieve the passages that answer it`.
  - **Parents.** `WorkerSettings` and `ApiSettings` both derive from `ProviderSettings`.
  - **`ApiSettings` additions.** `ANSWER_MODEL_URL: HttpUrl` (required), `ANSWER_MODEL: str` (required, `min_length=1`), `ANSWER_MODEL_TIMEOUT_SECONDS=60`, `ANSWER_MAX_TOKENS=800`, `ANSWER_TEMPERATURE=0` (`ge=0`, `le=2`), `RETRIEVAL_TOP_K=8`, `MIN_SIMILARITY=0.60` (`ge=0`, `le=1`), `LOW_CONFIDENCE_THRESHOLD=0.90` (`ge=0`, `le=1`), `MAX_QUESTION_CHARS=2000`, `MAX_FILTER_DOCUMENTS=20`, `ANSWER_CONCURRENCY=2`, `ANSWER_QUEUE_LIMIT=10` (`ge=0`), `ANSWER_DEADLINE_SECONDS=90`.
  - **Validator.** A model validator raises "ANSWER_MODEL_TIMEOUT_SECONDS must be shorter than ANSWER_DEADLINE_SECONDS".
  - **Retry policy.** Change `RetryPolicy.for_providers` in `backend/src/multimodal_rag/shared/resilience.py` to take `ProviderSettings`.
  - **Tests.** Extend `backend/tests/unit/shared/test_config.py` for the new defaults, the required answer model settings and the validator, and keep `backend/tests/unit/shared/test_resilience.py` passing.
- [x] T006 [P] Add `BoundingBox.gap_to(other) -> float` to `backend/src/multimodal_rag/ingestion/domain.py`: the shortest distance between two boxes on the same page in PDF points, 0 when they touch or overlap. Add cases (overlap, side by side, above, diagonal) to `backend/tests/unit/ingestion/test_domain.py`.
- [x] T007 Implement the answering domain in `backend/src/multimodal_rag/answering/domain.py` as frozen, slotted dataclasses and `StrEnum`s, exactly as [data-model.md](data-model.md) defines them:
  - **`Question`.** `text` is trimmed and holds "1 to `MAX_QUESTION_CHARS` (2,000) characters, else `InvalidQuestionError`". When `document_ids` is set it holds "1 to `MAX_FILTER_DOCUMENTS` (20) distinct ids". Build it through a `Question.create(text, *, document_ids, max_chars, max_documents)` factory.
  - **Enums.** `AnswerStatus` (`answered`, `not_enough_information`) and `NotEnoughReason` (`no_searchable_documents`, `no_relevant_content`, `not_answered_by_sources`, `no_valid_citations`).
  - **Entities.** `Citation`, `RetrievedSource`, `TableContent`, `AnswerImage`, `Answer`, `GroundedPrompt` and `GeneratedAnswer`. `Answer` provides a `not_enough(reason, text)` constructor that leaves citations, sources and images empty.
- [x] T008 [P] Implement the answering errors in `backend/src/multimodal_rag/answering/errors.py` with the codes and families of research section 11. Each 5xx error has a fixed message without provider data:
  - Validation and state: `InvalidQuestionError`, `UnknownDocumentsError` (holds and names the ids), `DocumentsNotReadyError` (holds and names the ids).
  - Capacity: `AnsweringBusyError`.
  - Search: `SearchUnavailableError`, `SearchTimeoutError`.
  - Answer model: `AnswerModelUnavailableError`, `AnswerModelTimeoutError`, `AnswerModelResponseError`, `AnswerDeadlineExceededError`.
- [x] T009 Define the answering ports as `typing.Protocol` with Google-style docstrings in `backend/src/multimodal_rag/answering/ports.py`:
  - `AnswerGenerator.generate(prompt: GroundedPrompt) -> GeneratedAnswer`
  - `AnswerSlots.admit()`, an async context manager that raises `AnsweringBusyError`
  - `LanguageIdentifier.identify(text: str, *, candidates: Sequence[str]) -> str`
- [x] T010 Extend the ingestion ports in `backend/src/multimodal_rag/ingestion/ports.py`:
  - `Embedder.embed_query(text: str) -> list[float]`.
  - `SearchHit.similarity: float`, the dense cosine similarity.
  - `ElementRepository.get_many(element_ids: Sequence[uuid.UUID]) -> tuple[ExtractedElement, ...]`.
  - `DocumentRepository.get_many(document_ids: Sequence[uuid.UUID]) -> tuple[Document, ...]`, which skips unknown ids.
  - The `search_hybrid` docstring states that a missing collection returns no hits.
- [x] T011 Update `backend/tests/fakes.py`:
  - **Existing fakes.** Implement the extended ports. The fake embedder's `embed_query` is deterministic, the in-memory index returns a configurable similarity per unit, and both repositories get `get_many`.
  - **New fakes.** `FakeAnswerGenerator` (scripted `GeneratedAnswer`s or errors, a delay, and a record of the prompts it received), `FakeAnswerSlots` (capacity and queue limit, raising `AnsweringBusyError`) and `FakeLanguageIdentifier` (fixed or keyword-based answers).
  - **Protocol check.** Extend `backend/tests/unit/test_fakes_match_ports.py` to the new ports.
- [x] T012 [P] Implement `embed_query` in `backend/src/multimodal_rag/adapters/openai_compatible/embedder.py`. It prefixes the text with `Instruct: {instruction}\nQuery:` (research section 2), takes the instruction as a keyword-only constructor argument, and sends one input. Add respx tests to `backend/tests/unit/adapters/test_openai_compatible.py`: the exact request body, and the vector returned.
- [x] T013 Extend `QdrantVectorIndex.search_hybrid` in `backend/src/multimodal_rag/adapters/qdrant/index.py` (research section 3):
  - **Similarity.** After the RRF query, run a second `query_points` with the same dense vector, `using=DENSE`, a `HasIdCondition` on the fused ids, `limit=len(ids)` and `SearchParams(exact=True)`. Set `SearchHit.similarity` from its scores. A fused id missing from that answer raises `DataInconsistencyError`.
  - **Missing collection.** A missing collection (404) returns `[]`.
  - **Tests.** Extend `backend/tests/integration/test_qdrant_index.py`: the similarity equals the cosine of known vectors, and a missing collection returns no hits. Extend `backend/tests/unit/adapters/test_qdrant_http.py` for the 404 path.
- [x] T014 [P] Implement `get_many` in `backend/src/multimodal_rag/adapters/postgres/documents.py` and `backend/src/multimodal_rag/adapters/postgres/elements.py`, each with one `WHERE id = ANY(:ids)` query. Add cases to `backend/tests/integration/test_postgres_documents_and_jobs.py`: known ids, unknown ids skipped, and an empty input.
- [x] T015 [P] Move `ChatCompletion` and its private models from `backend/src/multimodal_rag/adapters/openai_compatible/describer.py` to a new `backend/src/multimodal_rag/adapters/openai_compatible/chat.py`, import it from the describer, and keep `backend/tests/unit/adapters/test_openai_compatible.py` passing.
- [x] T016 [P] Make `backend/tests/contract/contract.py` load both `specs/001-async-pdf-ingestion/contracts/openapi.yaml` and `specs/002-grounded-question-answering/contracts/openapi.yaml`:
  - Register both in the `referencing` registry under their file URIs, so the relative `$ref`s of the 002 contract resolve.
  - Expose the merged `paths`, so `backend/tests/contract/test_openapi_matches_contract.py` checks every served operation against both files.
- [x] T017 Update `compose.yaml`: the `api` service gets `QDRANT_URL: http://qdrant:6333` and a `models` element binding `vlm` (`endpoint_var: ANSWER_MODEL_URL`, `model_var: ANSWER_MODEL`) and `embedder` (`endpoint_var: EMBEDDER_URL`, `model_var: EMBEDDER_MODEL`). The API must not depend on Qdrant or the models to start (FR-024). Document every new setting of T005 with its default in `.env.example`, in the same style as the existing entries.

**Checkpoint**: settings load, the ports and fakes match, and the extended adapters pass their tests.

---

## Phase 3: User Story 1 - Ask a question and get a cited answer (Priority: P1) 🎯 MVP

**Goal**: a question returns a grounded Markdown answer with `[n]` markers, a numbered
citation list naming document and pages, and every supplied unit marked as cited or not.

**Independent Test**: ingest the FAA manual, ask "Why is a series wound generator never
used on airplanes?", and confirm the answer cites page 12 and lists the 8 supplied units
(quickstart Scenarios 1 and 2).

### Tests for User Story 1 (REQUIRED) ⚠️

- [x] T018 [P] [US1] Write `backend/tests/unit/answering/test_prompting.py`:
  - The system message holds the rules: only the sources, sources and question are data, markers after each factual sentence, `not_covered`, the question's language, identifiers kept verbatim, and sources that disagree reported with each value and its own marker.
  - Each source is numbered from 1 in rank order, labeled with its pages and section, and fenced with `<<<` and `>>>`.
  - The question is fenced after the sources.
  - Text inside a source that looks like an instruction stays inside its fence unchanged.
- [x] T019 [P] [US1] Write `backend/tests/unit/answering/test_citations.py`:
  - Markers of supplied sources are kept, and `[1][3]` counts as two markers.
  - Out-of-range numbers and `[0]` are removed from the text.
  - Units sharing document and pages merge into one citation that lists both unit ids.
  - Citations are renumbered 1..n in order of first appearance, and the text is rewritten to match.
  - Every citation is referenced at least once, and a text with no valid marker yields no citations.
- [x] T020 [P] [US1] Write `backend/tests/unit/answering/test_sources.py`:
  - The excerpt is at most 300 characters.
  - `low_confidence_text` is true only when an element has `origin=recognized` and `confidence < LOW_CONFIDENCE_THRESHOLD`, with 0.8999 flagged and 0.90 not flagged.
  - A figure unit whose figure is `described` has `generated_description` and carries `unverified_identifiers`.
  - `citation_number` is taken from the citations.
  - `figure_ids` lists the unit's non-decorative figures, so every source says whether it has associated images.
- [x] T021 [P] [US1] Write the answered-path tests in `backend/tests/unit/answering/test_ask.py`, using fakes:
  - The answer has status `answered`, reason `None` and up to `RETRIEVAL_TOP_K` sources in rank order.
  - Citations name the document file name and pages, and a unit spanning pages 3 and 4 is cited with both.
  - The prompt the generator received holds the sources in rank order.
  - One log record per question has the outcome, the unit count and the timings, and contains neither the question nor the answer text (FR-026).
  - A hit whose document is missing from `DocumentRepository.get_many` raises `DataInconsistencyError` instead of a citation without a name.
  - Two consecutive questions to the same `AnswerQuestion` produce prompts that share nothing but the rules, so each question is answered independently (FR-021).
- [x] T022 [P] [US1] Write `backend/tests/unit/adapters/test_openai_answerer.py` with respx:
  - The request body carries `model`, the two messages, `temperature`, `max_tokens`, `chat_template_kwargs.enable_thinking=false` and `response_format` of type `json_schema` with the `answer`/`not_covered` schema.
  - A valid JSON content becomes a `GeneratedAnswer`.
  - Content that is not JSON, or does not match the schema, raises `AnswerModelResponseError`.
  - A 503 is retried and then raises `ProviderUnavailableError`.
- [x] T023 [P] [US1] Write `backend/tests/contract/test_questions_contract.py`: with the use case backed by fakes, `POST /api/v1/questions` returns 200 and a body valid against the `Answer` schema of the 002 contract, and a malformed body returns 400 `invalid_request` as problem JSON.

### Implementation for User Story 1

- [x] T024 [P] [US1] Implement `build_prompt(question, hits) -> GroundedPrompt` in `backend/src/multimodal_rag/answering/prompting.py` with the rules of research section 5, including the rule for sources that disagree, as module constants with a one-line comment on why the question and sources are fenced.
- [x] T025 [P] [US1] Implement marker validation, merging and renumbering in `backend/src/multimodal_rag/answering/citations.py` (research section 6). It returns the rewritten text, the citations, and a mapping from unit id to citation number.
- [x] T026 [P] [US1] Implement source assembly in `backend/src/multimodal_rag/answering/sources.py`: excerpt, flags from the unit's elements, the unit's non-decorative `figure_ids`, and citation numbers (research section 8). Tables are added in US4.
- [x] T027 [P] [US1] Implement `OpenAICompatibleAnswerGenerator` in `backend/src/multimodal_rag/adapters/openai_compatible/answerer.py`:
  - **Transport.** Use `post_json` and `ChatCompletion` from `chat.py`, with the `json_schema` response format of research section 5.
  - **Constructor.** Takes `model`, `max_tokens`, `temperature` and `retry`, keyword-only.
  - **Validation.** Validate the content with a pydantic model, because llama-server may ignore a grammar.
- [x] T028 [US1] Implement `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py` for the answered path:
  - **Steps.** Build the `Question`, embed the query, run `search_hybrid` with `limit=RETRIEVAL_TOP_K`, load the elements with `get_many` and the documents with `get_many`, build the prompt, generate, validate the citations, and assemble the sources.
  - **Integrity.** A hit whose document is not returned by `get_many` raises `DataInconsistencyError` (spec edge case), never a source without a document name.
  - **Timings and logs.** Measure search and generation times with `time.perf_counter`, and log one record per question as FR-026 requires.
  - **Constructor.** Ports and options are injected through the constructor, keyword-only.
- [x] T029 [US1] Add `QuestionBody`, `AnswerBody`, `CitationBody`, `SourceBody` and `TableContentBody` to `backend/src/multimodal_rag/adapters/http/schemas.py`, mirroring `contracts/openapi.yaml` of 002. `SourceBody.cited` is `citation_number is not None`. `QuestionBody.question` is a plain string with no length limit in the schema, because `Question.create` enforces the configurable `MAX_QUESTION_CHARS` and answers `invalid_question`.
- [x] T030 [US1] Add `AnsweringState` and `provide_answer_question` to `backend/src/multimodal_rag/adapters/http/dependencies.py`. Implement `POST /api/v1/questions` (`operation_id="askQuestion"`) in the new `backend/src/multimodal_rag/adapters/http/routes_questions.py`, which only translates the body to a `Question` call and the `Answer` back to `AnswerBody`.
- [x] T031 [US1] Wire answering in `backend/src/multimodal_rag/bootstrap.py`:
  - Build the Qdrant client and index, the embedder, the answer generator and the repositories from `ApiSettings`.
  - Close the clients in the lifespan, merge `AnsweringState` into the lifespan state, and register the questions router.
  - Extend `backend/tests/unit/test_bootstrap.py` so the app builds with the new required settings.

**Checkpoint**: User Story 1 answers cited questions end to end (quickstart Scenarios 1 and 2).

---

## Phase 4: User Story 2 - Say so when the documents do not contain the answer (Priority: P1)

**Goal**: questions the documents do not support return `not_enough_information` with a
reason, no citations and no images. The model is never asked when nothing relevant was
retrieved.

**Independent Test**: ask about paella and about a Boeing 737 APU torque, and confirm
`not_enough_information` with no citation, source or image, and no model call for the
first (quickstart Scenario 3).

### Tests for User Story 2 (REQUIRED) ⚠️

- [x] T032 [P] [US2] Write the similarity cases of `backend/tests/unit/answering/test_relevance.py`: a hit at `MIN_SIMILARITY` passes, one just below fails, and the gate passes when any hit passes.
- [x] T033 [P] [US2] Write `backend/tests/unit/answering/test_messages.py`: every `NotEnoughReason` has an English and a Spanish message, an unknown language falls back to English, and no message is empty.
- [x] T034 [P] [US2] Add the not-enough cases to `backend/tests/unit/answering/test_ask.py`. This is the constitution's required test for insufficient context.
  - **No hits.** Reason `no_searchable_documents`, and the generator is never called.
  - **Gate fails.** Reason `no_relevant_content`, the generator is never called, and the text is the Spanish message for a Spanish question.
  - **Empty model answer.** Reason `not_answered_by_sources`, with the model's `not_covered` as text.
  - **Only invalid markers.** Reason `no_valid_citations`.
  - **Partial answer.** Stays `answered` and carries `not_covered`.
  - **Every not-enough outcome.** No citations, sources or images.
- [x] T035 [P] [US2] Write `backend/tests/unit/adapters/test_py3langid_identifier.py`: English and Spanish short questions from quickstart are identified among `["en", "es"]`, and the result is always one of the candidates.

### Implementation for User Story 2

- [x] T036 [P] [US2] Implement the similarity gate `passes_gate(hits, *, min_similarity) -> bool` in `backend/src/multimodal_rag/answering/relevance.py`.
- [x] T037 [P] [US2] Implement the fixed messages per `NotEnoughReason` in English and Spanish in `backend/src/multimodal_rag/answering/messages.py`, with `SUPPORTED_LANGUAGES = ("en", "es")` and an English fallback.
- [x] T038 [P] [US2] Implement `Py3LangidIdentifier` in `backend/src/multimodal_rag/adapters/language/py3langid_identifier.py`, restricted to the candidates on each call. Load the model once at construction, not per request.
- [x] T039 [US2] Extend `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py`: no hits, the gate before generation, an empty answer and no valid citation, each building `Answer.not_enough` with the reason and the text of data-model.md. The `LanguageIdentifier` is injected, and the outcome reason is logged.
- [x] T040 [US2] Wire `Py3LangidIdentifier` and `MIN_SIMILARITY` into `AnswerQuestion` in `backend/src/multimodal_rag/bootstrap.py`.

**Checkpoint**: Stories 1 and 2 give the full grounded behavior (quickstart Scenario 3).

---

## Phase 4b: Grounding hardening after the reference audit (US1 and US2)

**Goal**: apply the practices measured in research sections 3 to 6 against the running
system and the reference projects, so correct answers are not lost for missing markers.

**Independent Test**: "What does a field rheostat do in a generator?", which the model
answers without markers, returns `answered` with citations, and quickstart Scenarios 1 to 3
still pass.

### Tests (REQUIRED) ⚠️

- [x] T074 [P] Add to `backend/tests/unit/answering/test_citations.py`: `[1, 3]`, `[1-3]`, `[[1]]` and `【1】` become separate markers, a range expands to at most the supplied sources, and an invalid number inside a variant is dropped.
- [x] T075 [P] Write `backend/tests/unit/answering/test_attribution.py`: statements are split by line and sentence, statements under three words get no marker, the marker goes before the final punctuation, the best unit by the 0.7 word share and 0.3 cosine score wins, a score below the minimum adds nothing, and word matching ignores accents and case.
- [x] T076 [P] Update `backend/tests/unit/answering/test_prompting.py` for `<sources>`, `<source id pages section document>`, `<question>`, the escaped closing tags and the abstention rule.
- [x] T077 [P] Add to `backend/tests/unit/adapters/test_openai_answerer.py`: `finish_reason` `length` raises `AnswerModelResponseError` and logs a warning.
- [x] T078 [P] Add to `backend/tests/unit/answering/test_relevance.py` and `backend/tests/unit/answering/test_ask.py`: identical unit texts keep only the best ranked one, the search asks for twice `RETRIEVAL_TOP_K`, an answer without markers is attributed and stays `answered`, and an answer that only cites unsupplied sources stays `no_valid_citations`.

### Implementation

- [x] T079 Rewrite marker variants in `backend/src/multimodal_rag/answering/citations.py` (research section 6).
- [x] T080 Implement `backend/src/multimodal_rag/answering/attribution.py`, reusing the sentence pattern of `backend/src/multimodal_rag/ingestion/retrieval_units.py`, and call it from `AnswerQuestion` when the answer has no marker. Add `ATTRIBUTION_MIN_SCORE` to `ApiSettings`, move `EMBEDDER_BATCH_SIZE` to `ProviderSettings`, and document both in `.env.example`.
- [x] T081 Build the XML source tags with document names and escaping in `backend/src/multimodal_rag/answering/prompting.py` (research section 5).
- [x] T082 Read `finish_reason` in `backend/src/multimodal_rag/adapters/openai_compatible/chat.py` and `answerer.py`.
- [x] T083 Add `distinct_hits` to `backend/src/multimodal_rag/answering/relevance.py` and use it in `AnswerQuestion` (research section 3).
- [x] T084 Build the answering clients inside the lifespan in `backend/src/multimodal_rag/bootstrap.py`, as Starlette's lifespan state documentation and Polar do.
- [x] T085 Rebuild the API and re-run quickstart Scenarios 1 to 3 and the 12 audit questions against the running system.

**Checkpoint**: the MVP keeps correct answers whose markers the model forgot, with every
citation still pointing to a supplied unit.

---

## Phase 5: User Story 3 - Find exact identifiers such as part numbers and error codes (Priority: P2)

**Goal**: questions about codes such as `SPL-480` reach the unit that contains them, even
when their meaning similarity is below the gate.

**Independent Test**: ask "What is code SPL-480?" and confirm the unit on page 13 of the
TM manual is supplied and cited (quickstart Scenario 4).

### Tests for User Story 3 (REQUIRED) ⚠️

- [x] T041 [P] [US3] Add the identifier cases to `backend/tests/unit/answering/test_relevance.py`:
  - Extraction finds `SPL-480`, `ODW-300` and `2-71`, and ignores words without digits and tokens shorter than three characters.
  - Matching ignores case and accents.
  - A hit below `MIN_SIMILARITY` that contains an identifier from the question passes the gate.
  - An identifier absent from every hit does not pass.
- [x] T042 [P] [US3] Add to `backend/tests/integration/test_qdrant_index.py`: a unit containing `SPL-480` ranks in the top `RETRIEVAL_TOP_K` for "What is code SPL-480?" through the BM25 side, even when its dense vector is far from the query vector.
- [x] T043 [P] [US3] Add to `backend/tests/unit/answering/test_ask.py`: an identifier question whose best similarity is 0.42 reaches the generator, and its answer cites the identifier's unit.

### Implementation for User Story 3

- [x] T044 [US3] Add `question_identifiers(text)` and the identifier rule to `backend/src/multimodal_rag/answering/relevance.py` (research section 3). It uses `re` and `unicodedata` from the standard library and extends `passes_gate` with a keyword-only `question` argument.
- [x] T045 [US3] Pass the question to the gate in `backend/src/multimodal_rag/answering/use_cases/ask.py`.

**Checkpoint**: identifier questions are answered (quickstart Scenario 4).

---

## Phase 6: User Story 4 - See the diagram the answer depends on (Priority: P2)

**Goal**: answers return at most one primary image, the figure closest to the most
relevant cited text, plus related images, and table sources carry their rows.

**Independent Test**: ask about the shunt generator wiring and confirm the primary image
is the figure next to the cited text, with its caption and a URL that returns a PNG
(quickstart Scenario 5).

### Tests for User Story 4 (REQUIRED) ⚠️

- [x] T046 [P] [US4] Write `backend/tests/unit/answering/test_images.py`:
  - A cited figure unit's own figure is primary.
  - Among the figures of one cited text unit, the one with the smallest `gap_to` on the same page wins.
  - The figures of the higher-ranked cited unit come first.
  - Decorative figures and figures without `image_key` are excluded.
  - No duplicates appear, the primary is not repeated among related images, and there is no primary when no cited unit has figures.
  - The caption comes from a `caption_of` relationship, and is `None` without one.
  - In `backend/tests/unit/answering/test_ask.py`: a selected image whose crop is missing from `BlobStorage` raises `DataInconsistencyError` (spec edge case), and the check runs only for the returned images.
- [x] T047 [P] [US4] Add table cases to `backend/tests/unit/answering/test_sources.py`: a table unit returns one `TableContent` per table element with its page and rows in order, a continued table returns both parts, and text units return no tables.
- [x] T048 [P] [US4] Add to `backend/tests/contract/test_questions_contract.py`: an answer with a primary image, related images and a table source validates against the contract, and `primary_image.url` is the path of `getDocumentImage` for that document and element.

### Implementation for User Story 4

- [x] T049 [US4] Implement `select_images(cited_units, elements, relationships) -> tuple[AnswerImage | None, tuple[AnswerImage, ...]]` in `backend/src/multimodal_rag/answering/images.py` (research section 7), using `BoundingBox.gap_to`.
- [x] T050 [US4] Add `TableContent` assembly to `backend/src/multimodal_rag/answering/sources.py`, reading `ExtractedElement.table` of each table element of the unit.
- [x] T051 [US4] Extend `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py`:
  - Load the figure elements of the cited units with `get_many`, and their relationships with `relationships_for`.
  - Fill `primary_image` and `related_images` only for `answered` outcomes.
  - Check with `BlobStorage.exists` that the crop of every returned image exists, and raise `DataInconsistencyError` when one is missing. Inject `BlobStorage` in `backend/src/multimodal_rag/bootstrap.py`.
- [x] T052 [US4] Add `AnswerImageBody` to `backend/src/multimodal_rag/adapters/http/schemas.py`. Build its `url` in `backend/src/multimodal_rag/adapters/http/routes_questions.py` with `request.url_for("get_document_image", ...)`, as the elements route does.

**Checkpoint**: answers show their diagram (quickstart Scenario 5).

---

## Phase 7: User Story 5 - Get a clear error when a component is slow or down (Priority: P2)

**Goal**: failures of the answer model or search end within the deadline with an error
naming the component. Too many questions get `answering_busy` at once, a disconnect
cancels the work, and uploads and status keep working.

**Independent Test**: point the API at an unreachable answer model, ask a question, and
get 503 `answer_model_unavailable` within the deadline while the library answers in under
2 seconds. Send 16 questions at once and get 4 `answering_busy` (quickstart Scenarios 7,
8 and 9).

### Tests for User Story 5 (REQUIRED) ⚠️

- [x] T053 [P] [US5] Add the failure cases to `backend/tests/unit/answering/test_ask.py`:
  - **Error translation.** Embedder and index `ProviderUnavailableError` become `SearchUnavailableError`, and their `ProviderTimeoutError` becomes `SearchTimeoutError`. The generator's `ProviderUnavailableError`, `ProviderTimeoutError` and `ProviderResponseError` become `AnswerModelUnavailableError`, `AnswerModelTimeoutError` and `AnswerModelResponseError`. Each keeps the original as `__cause__`.
  - **Deadline.** A generator slower than the deadline raises `AnswerDeadlineExceededError`, and so does a question that waits for a slot beyond it.
  - **Busy.** A full `FakeAnswerSlots` raises `AnsweringBusyError` before any search.
  - **Invalid question.** An empty or 2,001-character question raises `InvalidQuestionError` before any port is called.
- [x] T054 [P] [US5] Write `backend/tests/unit/adapters/test_anyio_slots.py`:
  - With capacity 1 and queue limit 1, the third concurrent admission raises `AnsweringBusyError` at once, while the second waits and then runs.
  - A cancelled waiter frees its place in the line.
  - A cancelled holder releases its token.
- [x] T055 [P] [US5] Write `backend/tests/unit/adapters/test_http_disconnect.py`: an ASGI call whose `receive` returns `http.disconnect` after the body cancels the running handler coroutine, observed through a `CancelledError` in a fake use case. A normal request returns its result.
- [x] T056 [P] [US5] Add to `backend/tests/unit/adapters/test_http_app.py`:
  - Each answering error maps to the status and code of research section 11.
  - The 5xx answering errors include their fixed `detail`, while other 5xx errors still omit it.
  - `answering_busy` carries `Retry-After: 10`.
  - While the questions route fails with `AnswerModelUnavailableError`, `GET /api/v1/documents` still returns 200.

### Implementation for User Story 5

- [x] T057 [US5] Implement `AnyioAnswerSlots` in `backend/src/multimodal_rag/adapters/concurrency/anyio_slots.py` over `anyio.CapacityLimiter(ANSWER_CONCURRENCY)`. Raise `AnsweringBusyError` when `available_tokens == 0` and `statistics().tasks_waiting >= ANSWER_QUEUE_LIMIT`, with no `await` between the check and the acquisition (research section 10).
- [x] T058 [US5] Extend `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py`:
  - Validate the question before admission.
  - Wrap admission and work in `asyncio.timeout(ANSWER_DEADLINE_SECONDS)` and translate `TimeoutError` to `AnswerDeadlineExceededError`.
  - Translate provider errors per component, and log retries and busy rejections at warning level.
- [x] T059 [US5] Implement `run_until_disconnect(request, operation)` in `backend/src/multimodal_rag/adapters/http/disconnect.py`: an anyio task group runs the operation next to a listener that awaits `request.receive()` until `http.disconnect` and then cancels the group. Use it in `backend/src/multimodal_rag/adapters/http/routes_questions.py`.
- [x] T060 [US5] Map the answering errors in `backend/src/multimodal_rag/adapters/http/problems.py`:
  - Add them to `_STATUS_BY_ERROR`, with the most specific first: 400, 409, 502, 503 and 504 as research section 11 lists, and `CapacityError` at 503.
  - Send `detail` for errors listed in a `_PUBLIC_SERVER_ERRORS` tuple.
  - Add `Retry-After: 10` to `AnsweringBusyError` responses.
- [x] T061 [US5] Wire `AnyioAnswerSlots` and the deadline into `AnswerQuestion` in `backend/src/multimodal_rag/bootstrap.py`.

**Checkpoint**: failures are bounded and specific, and ingestion is unaffected (quickstart Scenarios 7 to 9).

---

## Phase 8: User Story 6 - Restrict a question to specific documents (Priority: P3)

**Goal**: a question limited to chosen documents uses only their content, and invalid
restrictions are rejected with the offending ids.

**Independent Test**: ask about generators restricted to the INSST guide and confirm every
source comes from it and the outcome is `not_enough_information`. Then restrict to an
unknown id and get 400 `unknown_documents` (quickstart Scenario 6).

### Tests for User Story 6 (REQUIRED) ⚠️

- [ ] T062 [P] [US6] Add restriction cases to `backend/tests/unit/answering/test_ask.py`:
  - Unknown ids raise `UnknownDocumentsError` naming exactly those ids, and ids whose latest job is not `completed` raise `DocumentsNotReadyError` naming them.
  - Both are raised before admission and before any search.
  - A valid restriction reaches `search_hybrid` as `document_ids`.
  - More than 20 ids, or duplicate ids, raise `InvalidQuestionError`.
- [ ] T063 [P] [US6] Add to `backend/tests/contract/test_questions_contract.py`: `document_ids` with an unknown id returns 400 `unknown_documents`, a pending document returns 409 `documents_not_ready`, and both are problem JSON.

### Implementation for User Story 6

- [ ] T064 [US6] Add the restriction check to `AnswerQuestion` in `backend/src/multimodal_rag/answering/use_cases/ask.py`, using `DocumentRepository.get_many` and `JobQueue.latest_for_documents`, and pass `document_ids` to `search_hybrid`. Inject `JobQueue` in `backend/src/multimodal_rag/bootstrap.py`.
- [ ] T065 [US6] Accept `document_ids` in `QuestionBody` in `backend/src/multimodal_rag/adapters/http/schemas.py` as an optional list of UUIDs with no count or uniqueness limit in the schema, and pass it through in `routes_questions.py`. `Question.create` enforces "1 to `MAX_FILTER_DOCUMENTS` (20) distinct ids" and answers `invalid_question`, as the contract describes.

**Checkpoint**: all six stories work independently.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: evaluation, documentation and final validation

- [ ] T066 [P] Write `backend/tests/evaluation/reference_questions.yaml`:
  - **Size.** At least 40 questions over the three sample manuals: paraphrased questions, identifier questions, figure questions, cross-language questions, at least one question whose sources disagree, and at least 10 unanswerable questions.
  - **Fields.** Each entry holds `id`, `question`, `language`, `expected_outcome` (`answered` or `not_enough_information`), `expected_document`, `expected_pages`, `expected_figure_page` (optional) and `kind`.
- [ ] T067 Write `backend/tests/evaluation/run_reference.py`:
  - **Run.** It posts every question to `--api` and computes SC-001 to SC-007 and SC-010, plus the top-similarity distribution of answerable and unanswerable questions.
  - **Language and latency.** SC-006 compares the question's language with the answer's, both identified with `py3langid`. SC-007 is the 95th percentile of the request time, measured with the model already loaded and again after an idle unload.
  - **Report.** It prints a table and exits non-zero when a criterion misses its target.
  - **Tests.** Its pure scoring functions are unit-tested in `backend/tests/evaluation/test_run_reference.py`, as `tests/load/` does for the backlog script.
- [ ] T068 Run `run_reference.py` against the running system. Tune `MIN_SIMILARITY` if the distribution shows a better cut, and record the results and the chosen value in `specs/002-grounded-question-answering/research.md` section 14.
- [ ] T069 [P] Extend `backend/tests/load/upload_backlog.py` with an option that asks questions while the backlog runs, and record SC-009 and SC-011 in `specs/002-grounded-question-answering/research.md` section 14.
- [ ] T070 [P] Write `docs/adr/0005-grounded-answers-and-relevance-gate.md` in the style of ADRs 0001 to 0004. It is written in business language, with the measurements of research sections 3, 5 and 14 in the technical annex.
- [ ] T071 [P] Update `docs/images/architecture.drawio.svg` with the question flow (API, embedder, Qdrant, PostgreSQL, answer model) using the drawio skill with official icons and capitalized labels. Update `README.md` with the question endpoint, an example request and response, the new settings, the evaluation command and ADR 0005 in the decision log.
- [ ] T072 Run `uv run --project backend pre-commit run --all-files` and `uv run --directory backend pytest --cov`, and keep coverage at or above 90%, adding unit tests in `backend/tests/unit/` where needed.
- [ ] T073 Run every scenario of `specs/002-grounded-question-answering/quickstart.md` against `docker compose up -d --build --wait` and fix any deviation. Also check whether the `api` service starts while Docker Model Runner is stopped. If the Compose `models` element blocks it, document that in `README.md` and in the plan, because FR-024 only covers failures after startup.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup and blocks every story. T005 precedes T017
  and the bootstrap tasks. T007 to T010 precede T011.
- **Phase 4b**: after US2 and before US3. It changes `citations.py`, `prompting.py`,
  `relevance.py`, `ask.py` and `bootstrap.py`, which later stories extend.
- **User stories (Phases 3 to 8)**: depend on Foundational. US1 is the base of the use
  case, so US2 to US6 extend `ask.py` after T028.
- **Polish (Phase 9)**: T066 to T069 need the running system with US1 to US4 done. T072
  and T073 come last.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on other stories.
- **US2 (P1)**: after US1's use case (T028).
- **US3 (P2)**: after US2's gate (T036).
- **US4 (P2)**: after US1. Independent of US2 and US3.
- **US5 (P2)**: after US1. Independent of US2 to US4.
- **US6 (P3)**: after US1. Independent of the others.

### Within Each User Story

- Tests are written first and fail before implementation.
- Pure core modules come before the use case, and the use case before the route and
  wiring.
- `ask.py`, `schemas.py`, `routes_questions.py` and `bootstrap.py` are shared, so tasks
  that touch them run in sequence.

### Parallel Opportunities

- **Foundational.** T004, T006, T008, T012, T014, T015 and T016 touch different files.
- **Within US1.** All tests (T018 to T023) run in parallel, and so do the core modules
  T024 to T027.
- **Across stories.** After US1, US4, US5 and US6 can proceed in parallel apart from the
  shared files listed above.
- **Polish.** T066, T069, T070 and T071 are independent.

---

## Parallel Example: User Story 1

```bash
# Tests for User Story 1 together:
Task: "Write backend/tests/unit/answering/test_prompting.py"
Task: "Write backend/tests/unit/answering/test_citations.py"
Task: "Write backend/tests/unit/answering/test_sources.py"
Task: "Write backend/tests/unit/adapters/test_openai_answerer.py"
Task: "Write backend/tests/contract/test_questions_contract.py"

# Core modules for User Story 1 together:
Task: "Implement build_prompt in backend/src/multimodal_rag/answering/prompting.py"
Task: "Implement backend/src/multimodal_rag/answering/citations.py"
Task: "Implement backend/src/multimodal_rag/answering/sources.py"
Task: "Implement backend/src/multimodal_rag/adapters/openai_compatible/answerer.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Complete Phases 1 and 2.
2. Complete US1 and validate quickstart Scenarios 1 and 2.
3. Complete US2 right after it. Both are P1, and a grounded system must admit gaps
   before it is demonstrated.
4. **Stop and validate** with quickstart Scenario 3.

### Incremental Delivery

1. US1 and US2 give grounded, cited answers.
2. US3 makes identifier questions reliable.
3. US4 adds the diagram next to the answer, the key multimodal requirement.
4. US5 bounds failures and load.
5. US6 adds document restriction.
6. Polish measures the success criteria and documents the decisions.

---

## Notes

- [P] tasks touch different files and have no dependency on unfinished tasks.
- Commit after each task or logical group, following Conventional Commits with the `qa`
  scope, for example `feat(qa): validate citations against retrieved units`.
- Stop at any checkpoint to validate a story on its own.
- Never log the question, the answer or document content.
