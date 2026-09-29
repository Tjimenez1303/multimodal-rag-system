# Data Model: Reranked Relevance Gate

Nothing is stored. The feature changes values that exist for the duration of one
question, defined by the question answering feature in
`specs/002-grounded-question-answering/data-model.md`. Only the changes are listed here.

## JudgedHit

A search hit together with the reranker's judgement of it. Internal to the answering
core, in `answering/domain.py`.

| Field | Type | Notes |
|---|---|---|
| `hit` | `SearchHit` | The unit, its fused score and its dense similarity, from the ingestion port |
| `relevance` | float in 0 to 1 | Probability that the unit contains the answer (FR-001) |

Selection and ordering (FR-007, research section 7):

- The first `RETRIEVAL_TOP_K` by descending `relevance`, then the order of the search,
  which is the fused rank, are kept.
- Every candidate that holds an identifier of the question as a whole token is kept too,
  each one replacing the lowest judged kept unit that holds none. When more than
  `RETRIEVAL_TOP_K` hold one, those with the highest relevance are kept.
- The kept units are ordered by descending `relevance`, then the order of the search.

## RetrievedSource

Gains one field. Every other field is unchanged.

| Field | Type | Notes |
|---|---|---|
| `relevance` | float in 0 to 1 | The unit's judged relevance (FR-008) |
| `rank` | integer ≥ 1 | Now the position in judged order, which is the order supplied to the answer model |
| `similarity` | float | Unchanged value. Informational only, it no longer gates (FR-006) |

## Ports

New port, in `answering/ports.py`:

| Port | Methods | Production adapter | Test fake |
|---|---|---|---|
| `RelevanceJudge` | `judge(question, passages) -> list[float]`, one relevance per passage in the same order | `adapters/openai_compatible/reranker.py` | `FakeRelevanceJudge` with relevance per passage text, a default and scripted failures |

The adapter receives the existing `TokenCounter` port to shorten passages. The answering
core never sees the prompt format, the instruction or the token budget.

`judge` raises the provider error families, as every provider port does:

- `ProviderUnavailableError` when the reranker stays unreachable after retries.
- `ProviderTimeoutError` when it keeps timing out after retries.
- `ProviderResponseError` when it rejects the request or answers without the log
  probabilities of `yes` or `no`.

## Errors

New errors, in `answering/errors.py`, following the pattern of the search and answer
model errors. Each carries a fixed message that names the reranker and no provider data.

| Error | Code | HTTP | Raised when |
|---|---|---|---|
| `RerankerUnavailableError` | `reranker_unavailable` | 503 | `judge` raised `ProviderUnavailableError` |
| `RerankerTimeoutError` | `reranker_timeout` | 504 | `judge` raised `ProviderTimeoutError` |
| `RerankerResponseError` | `reranker_invalid_response` | 502 | `judge` raised `ProviderResponseError` |

## Settings

`ApiSettings` gains the reranker settings of [research.md](research.md), section 9, and
loses `min_similarity`. `embedder_tokenizer_path` moves from `WorkerSettings` to
`ProviderSettings`. New validators:

- `RERANK_CANDIDATES` must be at least `RETRIEVAL_TOP_K`.
- `RERANKER_TIMEOUT_SECONDS` must be shorter than `ANSWER_DEADLINE_SECONDS`.

## Validation rules from the spec

| Rule | Source | Where enforced |
|---|---|---|
| Every candidate is judged, and judged relevance is in 0 to 1 | FR-001 | `RelevanceJudge` adapter, checked by its respx tests |
| The judgement reads the question and the passage together, with the task instruction | FR-002, FR-003 | Adapter prompt, `RERANKER_INSTRUCTION` |
| Up to `RERANK_CANDIDATES` distinct candidates judged, `RETRIEVAL_TOP_K` supplied | FR-004 | `AnswerQuestion` search and selection |
| No model call unless a supplied unit reaches `MIN_RELEVANCE` or holds an identifier | FR-005 | `answering/relevance.py`, checked before generation |
| The dense similarity does not gate | FR-006 | `answering/relevance.py` |
| Supplied units in judged order, search rank on ties | FR-007 | `answering/relevance.py`, stable sort over the search order |
| Candidates holding a question identifier always supplied | FR-007, SC-007 | `answering/relevance.py`, with `question_identifiers` |
| Every source carries its relevance | FR-008 | `answering/sources.py` and the HTTP schema |
| Long passages shortened to fit, never failing on length | FR-009 | Adapter, through `TokenCounter.truncate` |
| Reranker failures named, no fallback | FR-011, FR-012 | `AnswerQuestion` failure mapping |
| Judging time and top relevance logged, no content | FR-014 | `AnswerQuestion` log line |
| Cancellation stops judging | FR-015 | Task group in the adapter, cancelled with the request |
