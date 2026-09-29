# 0009. A reranker decides whether a question is answered

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Before this decision, the system asked the answer model only when a retrieved passage
was close enough in meaning to the question (ADR 0005). That closeness is measured
between two summaries computed separately, one of the question and one of the passage,
and it behaves badly in both directions.

- A technician who types a label, such as "Total Neto", is told the documents do not
  contain the answer, even when the page that shows the total is the first result by a
  wide margin. Short questions look less alike to a long passage than full sentences do.
- A question about something the documents never say, such as the number of employees
  of a company whose profile describes its services, looks close to the profile and
  reaches the model. The technician waits 6 to 13 seconds for "not enough information".

How should the system decide that the retrieved passages answer the question?

## Decision drivers

- Short and keyword-style questions whose answer is written in a document get an answer
  (FR-005).
- Questions on a document's topic that it does not answer stop before the model, so
  they cost no model time (FR-002).
- Part numbers and error codes found by keyword search still reach the model (FR-007).
- Everything runs locally, with the models Docker Model Runner already serves.
- The decision takes a fraction of a second next to an answer.

## Considered options

1. A reranker, a second model that reads the question and each passage together and
   judges whether the passage answers it.
2. Lowering the closeness threshold.
3. Counting how many of the question's words appear in the passage, as RAGFlow does.
4. No gate, letting the answer model decide every time.

## Decision outcome

Chosen option: **a reranker decides whether a question is answered**.

- Search still combines meaning and exact keywords. The 16 best distinct passages are
  handed to the reranker, which gives each one the probability that it contains the
  answer.
- The 8 passages with the highest probability are given to the answer model, best first.
  A passage that holds a code the question names, such as `SPL-480`, is always among
  them.
- The model is asked only when one of those passages reaches a probability of 0.30, or
  holds a code of the question. Otherwise the answer is "not enough information" at
  once.
- The reranker is told to judge whether the passage contains the information that
  answers the question, not whether it is on the same subject.
- Every source listed with an answer shows its probability. The closeness in meaning
  stays as information and no longer decides anything.
- When the reranker is down, the question fails with an error that names it. The system
  never falls back to the old check, which would bring its rejections back silently.

### Consequences

- Good, because a label typed on its own, such as "Total Neto", is answered from the
  page that shows it.
- Good, because questions near a document's topic that it does not answer are stopped
  in about two seconds instead of after the answer model.
- Good, because the answer model reads the passage that answers the question first.
- Good, because the reranker belongs to the same model family as the embedding model,
  so it reads English and Spanish and a question in one about a passage in the other.
- Bad, because it is a third local model, about 1.2 GB of memory, and a new component
  that can fail.
- Bad, because judging adds about 1.4 seconds to a typical question, and up to 2.5
  seconds when many long table passages are retrieved.
- Bad, because a few short questions stay out of reach of a model this small, such as
  asking for a contact email when the passage shows only the address itself. A larger
  reranker is the next option if they matter.
- Bad, because the threshold was set on 31 questions. The labeled evaluation set
  confirms or tunes it.

## Annex: technical evidence

### Measured gates

31 labeled questions over the documents indexed on 2026-09-29: 18 answerable, 9 on a
document's topic that it does not answer, and 4 unrelated. Each used the live hybrid
search, and 8 candidates were judged.

| Gate | Answerable let through | Topic without answer let through | Unrelated let through |
|---|---|---|---|
| Cosine similarity ≥ 0.60 (ADR 0005) | 8 of 18 | 5 of 9 | 0 of 4 |
| `/rerank` endpoint, default instruction, ≥ 0.5 | 14 of 18 | 4 of 9 | 0 of 4 |
| Reranker with this project's instruction, ≥ 0.30 | 15 of 18 | 0 of 9 | 0 of 4 |

- "Total Neto" and "Cual es mi total Neto" scored 0.43 and 0.48 in cosine similarity and
  0.997 and 0.995 with the reranker.
- The lowest accepted answerable questions scored 0.380 to 0.401. The highest question
  without an answer scored 0.278, so 0.30 sits in the gap.
- Short answerable questions, of one to three words, went from 2 of 9 let through to 7
  of 9.
- On the sample manuals, judging 16 candidates took 1.4 s at the median and 2.5 s at
  the 95th percentile, because table passages run up to 2,048 tokens. Judging 8 took
  0.9 s at the median, but a distance held in a table no longer reached the answer
  model, so 16 are judged.

### Labeled evaluation

58 questions over the two digital sample manuals and the invented maintenance quote,
asked through the running API with 16 candidates:

| Criterion | Result |
|---|---|
| Answerable questions that reach the answer model | 36 of 36 |
| Answerable questions of one to three words | 18 of 18 |
| Questions without an answer stopped before the answer model | 15 of 22 |
| Questions without an answer that end as "not enough information" | 21 of 22 |
| Identifier questions whose passage is given to the model | 9 of 9 |

Six of the seven questions without an answer that passed are near misses the answer
model then declined, such as a distance for a voltage one row past the end of a table.
The seventh passed because the year "2019" counts as a code under ADR 0005's rule.

### Scoring

Qwen3-Reranker-0.6B (`ai/qwen3-reranker:0.6B`, 1.2 GB) judges a passage by answering
"yes" or "no" to the model card's judging prompt, and the relevance is
`exp(yes) / (exp(yes) + exp(no))` over the log probabilities of the first generated
token. Each passage is one `chat/completions` request with `max_tokens` 1, `logprobs`
and `top_logprobs` 20, and thinking disabled, so the served chat template produces the
model card's prompt exactly: on four pairs, the chat request and a hand-written raw
prompt gave the same score to four decimals.

The instruction decides the questions without an answer. A question for a company's
number of employees, against the company description, scored 0.929 with the model
card's default web-search instruction and 0.084 with "Given a question about a document,
judge whether the passage contains the information that answers it".

### Why not the other options

- **The `/rerank` endpoint** of Docker Model Runner answers with the same scores, but
  llama.cpp fixes its instruction to web search, and a custom one is only in an open pull
  request. It also needs the model in reranking mode with a batch that holds the longest
  passage.
- **A lower cosine threshold** cannot separate the sets: questions without an answer
  scored up to 0.737, above every short answerable question.
- **Word coverage**, RAGFlow's term similarity, rescued none of the rejected answerable
  questions.
- **No gate**, the default of OpenAI's file search and LlamaIndex, spends 6 to 13 seconds
  of the answer model on every unrelated question.

### Codes of the question

Identifiers carry little meaning for a model, so their passage can be judged below prose
that shares the question's words. RAGFlow keeps exact term evidence after its reranker,
blending term similarity into the final score in `rerank_by_model`, and Anthropic's
Contextual Retrieval keeps BM25 next to its reranker for error codes. This system keeps
the narrower rule of ADR 0005: a passage that holds a code of the question as a whole
token is always given to the model and lets the question through.

### Long passages

Tables are never split at ingestion, and some table passages of a microcontroller
datasheet reach 37,498 characters. Each judging request holds at most 2,048 tokens, one
of the reranker's four slots of its 8,192-token context, so longer passages are cut to
a prefix that keeps their headings. The tokenizer the image already bakes for the
embedding model counts the reranker's tokens exactly, plus one end-of-text token.

### Sources

- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://hub.docker.com/r/ai/qwen3-reranker
- https://github.com/ggml-org/llama.cpp/pull/15824
- https://learn.microsoft.com/en-us/azure/search/semantic-search-overview
- https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-query
- https://docs.cohere.com/docs/reranking-best-practices
- https://www.anthropic.com/news/contextual-retrieval
- https://github.com/infiniflow/ragflow/blob/v0.27.2/rag/nlp/search.py
- Full analysis: `specs/004-reranked-relevance-gate/research.md`
