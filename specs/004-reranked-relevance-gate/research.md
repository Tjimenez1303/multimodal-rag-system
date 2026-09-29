# Research: Reranked Relevance Gate

Every decision below was checked against official documentation or source code, or
measured on the reference machine on 2026-09-29 against the documents indexed that day:
a company profile in Spanish (6 pages), the ESP32 datasheet in English (78 pages) and the
units of a repair budget in Spanish (2 pages). The reference machine is the one
described in `specs/001-async-pdf-ingestion/research.md`, with the models on the host GPU
through Docker Model Runner. The measurements are listed in section 12.

## 1. What this feature reuses

**Decision**: the feature adds one port and one adapter, and changes how the answering
use case selects, orders and gates the units it already retrieves.

| Existing piece | Use in this feature | Change |
|---|---|---|
| `VectorIndex.search_hybrid` and `distinct_hits` | Candidates to judge | The search asks for `RERANK_CANDIDATES × SEARCH_OVERFETCH` hits instead of `RETRIEVAL_TOP_K × SEARCH_OVERFETCH` |
| `answering/relevance.py` (`passes_gate`, `question_identifiers`) | The gate | The threshold reads the judged relevance instead of the dense similarity. The identifier rule is unchanged |
| `ChatCompletion` and `post_json` in `adapters/openai_compatible/` | Calls to the reranker | None. The reranker is called in the OpenAI chat format with `logprobs` |
| `TokenCounter` port and `HuggingFaceTokenCounter` | Shortening long passages | The API loads the tokenizer the image already bakes. `EMBEDDER_TOKENIZER_PATH` moves from the worker settings to the shared provider settings |
| `RetryPolicy`, `call_with_retry`, `provider_errors` | Retries and error families | None |
| The `_named` failure mapping in `AnswerQuestion` | Naming reranker failures | One more mapping, like search and the answer model have |
| Problem details in `adapters/http/problems.py` | Error responses | Three new error classes in the same table |
| The Compose `models` element | Provisioning the reranker | One more model, bound to the API only |

**Rationale**: the constitution requires reuse before new code. The reranker speaks the
same OpenAI-compatible protocol as the answer model and is served by the same Docker
Model Runner, so the transport, retries and error mapping already exist.

**Alternatives considered**: a reranking library inside the API process, such as
sentence-transformers' `CrossEncoder`. It would load PyTorch and the model weights into
the API container and run on the CPU, while Docker Model Runner already runs models on the
host GPU and the project's other models are served there (ADR 0003).

## 2. How reference systems decide that retrieved content is relevant

**Decision**: gate on a cross-encoder judgement of each retrieved passage, calibrated on
this system's own questions, and keep the answer model's abstention as the second line.

| System | Gate | Signal | Default | Source |
|---|---|---|---|---|
| Azure AI Search semantic ranker | Reranker score on a 0 to 4 scale, where 0 is irrelevant and 4 answers completely | Cross-encoder | None | https://learn.microsoft.com/en-us/azure/search/semantic-search-overview |
| Azure AI Search vector `threshold` | Minimum `vectorSimilarity`. Hybrid queries "aren't conducive to minimum thresholds" because RRF scores are small and volatile | Cosine | None | https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-query |
| Azure-Samples/azure-search-openai-demo | Keeps a document when `reranker_score >= minimum_reranker_score` (`app/backend/approaches/approach.py`) | Cross-encoder | 0 in the backend, 1.9 sent by the UI (`app/frontend/src/pages/chat/Chat.tsx`) | https://github.com/Azure-Samples/azure-search-openai-demo |
| Vertex AI RAG Engine | Optional `vector_distance_threshold`, optional semantic or LLM ranker | Cosine or ranker | None | https://github.com/googleapis/python-aiplatform (`vertexai/rag/utils/resources.py`) |
| OpenAI `file_search` | `ranking_options.score_threshold` | Ranker | 0 | https://github.com/openai/openai-python (`types/beta/file_search_tool.py`) |
| Anthropic Contextual Retrieval | No threshold. Hybrid retrieval then reranking of the top 150 to 20. Reranking cut top-20 retrieval failures by 67% together with contextual embeddings and BM25 | Cross-encoder | None | https://www.anthropic.com/news/contextual-retrieval |
| LangChain, LlamaIndex, Haystack | Optional cosine or reranker cutoff | Either | None or 0 | `langchain_core/vectorstores/base.py`, `llama_index/core/postprocessor/node.py`, haystack-core-integrations |
| RAGFlow | `0.3 × cosine + 0.7 × term coverage`, or the reranker score in place of the cosine | Fused | 0.2 | https://github.com/infiniflow/ragflow (`rag/nlp/search.py`) |
| Cohere Rerank | Scores in 0 to 1 that are "not proportional". Calibrate a threshold on 30 to 50 domain queries | Cross-encoder | Calibrate | https://docs.cohere.com/docs/reranking-best-practices |

**Rationale**:

- No reference system ships an absolute cutoff on the bi-encoder cosine by default, and
  Azure advises against thresholds on hybrid scores. Steck et al. show that cosine
  similarity of learned embeddings can yield arbitrary values (arXiv 2403.05440), and
  short queries against long passages are the asymmetric case where it is weakest.
- The systems that gate on a score use a cross-encoder, which reads the question and the
  passage together, and calibrate its threshold on their own domain.
- Every system still tells the answer model to say it does not know. This project already
  does, and FR-008 of the question answering feature requires it.

**Alternatives considered**: see section 6.

## 3. Reranker model and serving

**Decision**: `ai/qwen3-reranker:0.6B`, served by Docker Model Runner in completion mode
with a context of 8,192 tokens, declared in the Compose `models` element and bound to the
API service as `RERANKER_URL` and `RERANKER_MODEL`.

**Rationale**:

- Qwen3-Reranker belongs to the same family as the embedding model the project uses, so
  it shares its tokenizer (section 7) and its multilingual training, which covers English
  and Spanish (FR-003).
- The model card defines the score as the probability of the token `yes` against `no`
  after a fixed judging prompt, so the score is a probability in 0 to 1 that is comparable
  across questions (FR-001).
- The 0.6B model is a 1.2 GB F16 GGUF. It runs on llama.cpp with Metal next to the
  embedding and answer models, and llama.cpp gained Qwen3-Reranker support in pull request
  15824.
- Completion mode is enough, because the score is read from the log probabilities of one
  generated token (section 4). The reranking mode of Docker Model Runner is not needed.

Sources: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B,
https://hub.docker.com/r/ai/qwen3-reranker, https://docs.docker.com/ai/model-runner/,
https://github.com/ggml-org/llama.cpp/pull/15824

## 4. Scoring method

**Decision**: the adapter sends one `chat/completions` request per passage with the
model card's judging prompt, `max_tokens` 1, temperature 0, `logprobs` and
`top_logprobs` 20, and thinking disabled with `chat_template_kwargs`. The relevance is
`exp(lp_yes) / (exp(lp_yes) + exp(lp_no))` over the log probabilities of the tokens `yes`
and `no` among the top 20. A token absent from the top 20 counts as probability 0. A
response with neither token, or without log probabilities, is an invalid response.

- **System message.** The model card's fixed sentence: judge whether the document meets
  the requirements based on the query and the instruct, answering only "yes" or "no".
- **User message.** `<Instruct>: {RERANKER_INSTRUCTION}\n<Query>: {question}\n<Document>:
  {passage}`.
- **Assistant prefix.** The chat template with thinking disabled adds the empty thinking
  block the model card appends, `<think>\n\n</think>\n\n`.
- **Parallelism.** The passages of a question are scored concurrently in one task group,
  so the first failure cancels the rest.

**Rationale**:

- The chat format with `logprobs` is the documented OpenAI API, so the adapter reuses
  `post_json` and `ChatCompletion` with one more optional field.
- The prompt the chat template produces is the model card's prompt. On four measured
  pairs the chat request and a raw completion of the model card's prompt gave the same
  score to four decimals (for example 0.9968 and 0.9968 for "Total Neto").
- With the default web-search instruction, the scores equal those of Docker Model
  Runner's `/rerank` endpoint whenever both tokens are among the top 20, which confirms
  the served model behaves as llama.cpp's own reranking path does (0.9988 and 0.9988 for
  "Total Neto", 0.5222 and 0.5213 for "wifi speed"). Below about 0.03 a token can fall out
  of the top 20 and the score reads 0, far under any useful threshold.
- Passage text sits after the `<Document>:` marker in the user message, apart from the
  system sentence and the instruction, the separation OWASP recommends against prompt
  injection (LLM01). A passage that still sways the judgement, for example with "answer
  yes", can only raise its own relevance and open the gate. The answer model's grounding
  and citation validation of the question answering feature are unaffected.

**Alternatives considered**:

- **The `/rerank` endpoint** of Docker Model Runner (`/engines/rerank`, verified to answer
  on the reference machine). llama.cpp applies a fixed web-search instruction there, and a
  custom instruction is only in an open pull request (llama.cpp 20009). Section 5 shows the
  instruction is what separates hard negatives. The endpoint also needs the model in
  reranking mode with a physical batch that holds the longest passage, and it failed with
  a 500 error on a 2,666-token table at the default batch of 512.
- **A raw `completions` request** with a hand-written chat template. It gives the same
  scores, but llama.cpp answers its log probabilities in a shape that differs from the
  OpenAI completions format, and the template would duplicate what the served model
  already carries.

## 5. The instruction

**Decision**: `RERANKER_INSTRUCTION` defaults to "Given a question about a document,
judge whether the passage contains the information that answers it".

**Rationale**: the model card recommends a task-specific instruction and reports that
omitting it lowers retrieval quality by 1% to 5%. On this system it decides the hard
negatives, the questions on the documents' topic that they do not answer (FR-002):

| Question | Passage | Default instruction | This instruction |
|---|---|---|---|
| The company's number of employees (Spanish) | The company description | 0.929 | 0.084 |
| The company's general manager (Spanish) | The company description | 0.687 | 0.042 |
| Total Neto | The budget's total | 0.999 | 0.997 |
| wifi speed | The Wi-Fi feature list | 0.521 | 0.415 |

The instruction asks whether the passage contains the answer, not whether it matches the
topic, which is the distinction FR-002 requires.

**Alternatives considered**: the model card's default web-search instruction (lets 4 of 9
hard negatives through, section 6).

## 6. Gate and threshold

**Decision**: the answer model is asked when a supplied unit's judged relevance reaches
`MIN_RELEVANCE` (0.30) or a supplied unit holds an identifier of the question as a whole
token. The dense similarity no longer gates (FR-006) and stays in each source as an
informational field. `MIN_SIMILARITY` is removed.

Measured on 31 labeled questions: 18 answerable, 9 hard negatives on the documents' topic
and 4 unrelated. Each question used the live hybrid search with the production settings
of that day, which judged the 8 distinct candidates `RETRIEVAL_TOP_K` selects, except the
budget questions, whose three units were judged directly because that document had been
removed from the library. Judging 16 candidates (section 7) can only raise a question's
best judgement, so hard negatives are the side at risk, and the threshold is confirmed
with 16 candidates against the extended reference set (section 11).

| Gate | Answerable let through | Hard negatives let through | Unrelated let through |
|---|---|---|---|
| Dense similarity ≥ 0.60 (current) | 8 of 18 | 5 of 9 | 0 of 4 |
| `/rerank`, default instruction, ≥ 0.5 | 14 of 18 | 4 of 9 | 0 of 4 |
| Judgement with this instruction, ≥ 0.5 | 12 of 18 | 0 of 9 | 0 of 4 |
| **Judgement with this instruction, ≥ 0.30** | **15 of 18** | **0 of 9** | **0 of 4** |
| Judgement with this instruction, ≥ 0.25 | 16 of 18 | 1 of 9 | 0 of 4 |

- **Answerable, lowest scores.** "valores" 0.401, "¿Qué loterías y juegos venden?" 0.397,
  "visión de la empresa" 0.380. They pass at 0.30 and fail at 0.50.
- **Hard negatives, highest scores.** "How much does an ESP32 chip cost?" 0.278, "What
  Arduino library do I use for the ESP32 Wi-Fi?" 0.230. They fail at 0.30.
- **Answerable, still rejected.** "wifi speed" 0.258, a question for a record number
  printed on the budget 0.049, and a three-word question for the provider's contact
  email 0.007. The dense similarity rejects them too (0.576, 0.449 and 0.410), and no
  measured signal separates them from the hard negatives.
- **Unrelated.** At most 0.017.

0.30 sits in the gap between the lowest accepted answerable question (0.380) and the
highest hard negative (0.278). The set is small, so the value is confirmed or tuned
against the extended reference set (section 11), as Cohere recommends.

**The identifier rule** is evaluated over the supplied units, and section 7 guarantees
that every candidate holding an identifier of the question is supplied. The gate
therefore never passes because of a unit the answer model does not receive, and never
fails because the ranking pushed an identifier's unit out of the supplied set.

**Alternatives considered**:

- **Lowering `MIN_SIMILARITY` to about 0.45.** Hard negatives scored up to 0.737 on the
  dense similarity, above every short answerable question, so no cosine threshold
  separates the sets.
- **RAGFlow's term coverage** (share of the question's words present in the unit), alone
  or combined with the cosine. It rescued none of the rejected answerable questions: the email question
  covers 0% because the unit shows only the address itself, and the record number
  question covers 50%, as much as the hard negative "¿Cuál es la garantía de la
  reparación?".
- **A margin between the first and second hit**, as Weaviate's autocut cuts result lists.
  Unrelated questions can also produce a wide margin, and a margin says nothing about
  whether the first hit answers.
- **No gate, as OpenAI and LlamaIndex default to.** Every unrelated question would spend
  6 to 13 seconds of the answer model.
- **A larger reranker, such as Qwen3-Reranker-4B.** Left out by the spec, and a later
  option if the remaining misses matter.

## 7. Candidates, ordering and passage length

**Decision**:

- The search returns up to `RERANK_CANDIDATES × SEARCH_OVERFETCH` hits (32 by default),
  `distinct_hits` keeps up to `RERANK_CANDIDATES` distinct texts (16), and all of them are
  judged.
- The `RETRIEVAL_TOP_K` units (8) with the highest relevance are supplied, in descending
  relevance, with the fused search rank breaking ties (FR-007). A source's `rank` is its
  position in that order.
- Candidates that hold an identifier of the question as a whole token are always
  supplied. Each one left out by its relevance takes the place of the lowest judged unit
  that holds no identifier, and the supplied units are then ordered by relevance as
  above. When more than `RETRIEVAL_TOP_K` candidates hold an identifier, the ones with
  the highest relevance are kept.
- Each passage is the unit's `embedding_text`, heading path first, shortened to fit
  `RERANKER_MAX_INPUT_TOKENS` (2,048) together with the prompt and the question. The
  shortening keeps a prefix at a token boundary with `TokenCounter.truncate`, so the
  headings and the beginning stay (FR-009).

**Rationale**:

- Identifiers such as part numbers carry little meaning for a model, which is why the
  question answering feature added the identifier rule (its research section 3), and a
  cross-encoder can judge their unit below prose that shares the question's words.
  Reference systems keep exact term evidence in the final ranking when a reranker is
  present: RAGFlow's `rerank_by_model` returns `tkweight * tksim + vtweight * vtsim`, a
  blend of term similarity and the reranker's score, with the term weight at
  `1 - vector_similarity_weight`, 0.7 by default (`rag/nlp/search.py`, lines 558 to 588
  and 676 to 684, at v0.27.2). Anthropic's Contextual Retrieval keeps BM25 next to the
  reranker for the same reason, naming error codes such as "TS-999". This project keeps
  that evidence with the narrower rule it already has, so the calibrated relevance scale
  of section 6 stays unchanged.
- Judging 16 candidates instead of 8 lets a relevant unit that the fused ranking placed
  ninth or lower reach the answer model. 16 passages of about 150 tokens were scored in
  538 ms, against 421 ms for 8, because the server processes them in parallel.
- The reranker shares the embedding model's tokenizer. On four texts, including a
  581-token table and the chat markers, the baked `tokenizer.json` counted exactly one
  token more than the reranker reported, the end-of-text token the embedding tokenizer
  appends. The count is therefore exact up to that one token, which errs on the safe side.
- 2,048 tokens is one slot of the 8,192-token context, which llama.cpp splits across 4
  slots, as measured for the answer model in `specs/002-grounded-question-answering/research.md`
  section 14.
- Table units are never split at ingestion, and the ESP32 datasheet has table units of
  up to 37,498 characters, several times one slot of the context. Without shortening, the
  server rejects such a passage and the question fails.

**Alternatives considered**: judging only the 8 units the fused ranking supplies today
(ordering improves, but a relevant unit ranked ninth is never seen). Cutting passages by a
character count (the tokenizer is already in the image and is exact).

## 8. Timeouts, retries and errors

**Decision**: the reranker is called with its own client and `RERANKER_TIMEOUT_SECONDS`
(15), retried through `RetryPolicy.for_providers` like every provider, and its time counts
toward `ANSWER_DEADLINE_SECONDS`. When it stays unavailable, times out or answers an
unusable body, the question fails with a specific error, and no fallback to the similarity
or to the search order exists (Clarification of 2026-09-29, FR-012).

| Error | Code | HTTP | Family |
|---|---|---|---|
| `RerankerUnavailableError` | `reranker_unavailable` | 503 | `ProviderUnavailableError` |
| `RerankerTimeoutError` | `reranker_timeout` | 504 | `ProviderTimeoutError` |
| `RerankerResponseError` | `reranker_invalid_response` | 502 | `ProviderResponseError` |

**Rationale**: the same shape as the search and answer model errors of the question
answering feature, section 11, so the HTTP mapping, the problem detail and the client's
error display need no new mechanism. The reranker runs on the same Docker Model Runner as
the embedding model, so a fallback would rarely find search working, and it would
silently bring back the rejections this feature removes. Azure AI Search offers both
behaviors through `semanticErrorHandling` (`partial` or `fail`), and this system takes
`fail`.

**Alternatives considered**: falling back to the dense similarity gate (rejected in the
clarification). Skipping the gate and asking the answer model (every question would pay
for the answer model while the reranker is down).

## 9. Configuration

| Setting | Default | Notes |
|---|---|---|
| `RERANKER_URL` | required | Injected by the Compose `models` element |
| `RERANKER_MODEL` | required | Injected by the Compose `models` element |
| `RERANKER_TIMEOUT_SECONDS` | 15 | Must be shorter than `ANSWER_DEADLINE_SECONDS` |
| `RERANKER_INSTRUCTION` | section 5 | Task sentence of the judging prompt |
| `RERANKER_MAX_INPUT_TOKENS` | 2048 | One slot of the reranker's context |
| `RERANK_CANDIDATES` | 16 | Must be at least `RETRIEVAL_TOP_K` |
| `MIN_RELEVANCE` | 0.30 | Replaces `MIN_SIMILARITY` |
| `EMBEDDER_TOKENIZER_PATH` | set by the image | Moves to the settings the API and the worker share |

The Compose file declares the model once:

```yaml
models:
  reranker:
    model: ai/qwen3-reranker:0.6B
    context_size: 8192
```

## 10. Observability

**Decision**: the per-question log line of the question answering feature gains
`ranking_ms` and `top_relevance` (FR-014). A reranker retry is logged at warning level by
the shared retry policy, as for every provider.

**Rationale**: the time spent judging is what SC-004 measures, and the top relevance of
rejected questions is what tunes `MIN_RELEVANCE`. Neither contains the question, the
answer or document content.

## 11. Evaluation

**Decision**: a labeled question file, `backend/tests/evaluation/relevance_questions.yaml`,
and a script, `backend/tests/evaluation/evaluate_relevance.py`, that asks every question
through the running API and reports SC-001 to SC-004 and SC-007.

- **The set.** Questions over the two digital sample manuals and `labeled_total.pdf`,
  documents the quickstart ingests, so any run can reproduce it. The text layer of the
  scanned manual holds only a scanning notice, so no expected page could be verified
  against it and it has no questions. The calibration of
  section 6 used two documents that are not in the repository, a company profile and a
  microcontroller datasheet, so its questions are not part of the set. The set holds
  what the spec's success criteria require:
  - At least 10 answerable questions of one to three words.
  - At least 10 hard negatives.
  - At least 3 answerable questions in Spanish about an English document and 3 in
    English about a Spanish document (FR-003).
  - Identifier questions, each with the identifier its unit must hold (SC-007).

  Each entry records its label (answerable, hard negative or unrelated) and, for
  answerable ones, the expected document.
- **Candidates.** It runs with the default of 16 judged candidates, so the threshold
  measured on 8 in section 6 is confirmed or tuned for the setting that ships.
- **What it reads.** The outcomes come from the public response. A question was stopped
  by the gate when its reason is `no_relevant_content`. Such a question returns no
  sources, so its best judgement is read from the API's log line, matched by the
  `X-Request-ID` of the response, and the script prints the distribution that tunes
  `MIN_RELEVANCE`.
- **Where it runs.** It needs the running models, so it is a script, like the backlog load
  script, and not part of the default test run or CI. Its scoring functions are
  unit-tested.

**Rationale**: the threshold is only as good as the questions it was measured on, and a
repeatable run makes a change of `MIN_RELEVANCE` evidence-based.

## 12. Measurements on the reference machine

| Measurement | Result |
|---|---|
| Judging 8 candidates of the live index, in parallel | 58 to 581 ms, median about 350 ms |
| Judging 16 passages of about 150 tokens, in parallel | 538 ms (8 passages: 421 ms) |
| Chat request against a raw completion of the model card's prompt | Same score to four decimals on 4 pairs |
| Default instruction against the `/rerank` endpoint | Same score to three decimals on the 5 pairs where both tokens were in the top 20 |
| Embedding tokenizer against the reranker's prompt tokens | One token more on every text, the appended end-of-text token |
| Largest table unit in the index | 37,498 characters (a microcontroller datasheet, pages 46 to 50) |
| Reranker model size | 1.2 GB (F16 GGUF) |

### Labeled evaluation on the running system

T035 asked the 58 questions of `backend/tests/evaluation/relevance_questions.yaml`
through the API on 2026-09-29, with the two digital sample manuals, the scanned manual
and `labeled_total.pdf` ingested.

| Criterion | 16 candidates (default) | 8 candidates |
|---|---|---|
| SC-001 answerable that reach the answer model | 36 of 36 | 36 of 36 |
| SC-002 short answerable that reach it | 18 of 18 | 18 of 18 |
| SC-003 unanswerable stopped by the gate | 15 of 22 (68%) | 15 of 22 (68%) |
| SC-003 unanswerable that end as not enough information | 21 of 22 (95%) | 22 of 22 |
| SC-004 95th percentile of questions stopped by the gate | 1.98 s | 1.03 s |
| SC-007 identifier passages given to the model | 9 of 9 | 8 of 9 |
| Judging time, median and 95th percentile | 1.39 s and 2.52 s | 0.92 s and 2.07 s |

- **Candidates.** Judging 8 met the first latency target of 1.5 s, but the table that
  holds the DPEL-1 distances no longer reached the answer model. The maintainer kept 16
  and set SC-004 to 2.5 s. The calibration of section 7 had measured short passages, and
  the manuals' table passages run up to the 2,048-token limit.
- **Threshold.** `MIN_RELEVANCE` stays at 0.30. The questions without an answer that
  passed scored 0.706 to 0.998, above answerable questions such as "reglas de oro"
  (0.681) and the quote's status (0.431), so no threshold separates them. They are near
  misses, such as the DPEL-1 distance for 500 kV when the table stops at 380 kV, and the
  answer model declined all but one of them.
- **Identifier rule.** "How many electrical accidents were recorded in Spain in 2019?"
  was judged 0.000 and still passed, because the identifier rule of the question
  answering feature counts the year "2019" as a code. Excluding plain numbers from that
  rule is a follow-up of its own.
- **Answer length.** In the evaluation runs, the broad short questions "electricidad
  estática" and "magneto timing" reached the answer model and their answers stopped at
  the 800-token limit, which the question answering feature reports as
  `answer_model_invalid_response`. That limit is a follow-up of its own.
- **Unrelated questions.** All five were judged 0.000.
