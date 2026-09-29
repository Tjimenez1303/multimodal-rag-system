# 0005. Grounded answers and a relevance gate

- **Status**: Accepted. The relevance gate is superseded by
  [ADR 0009](0009-reranked-relevance-gate.md)
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

A technician acts on the answer. A wrong torque value or a made-up procedure can damage
an engine or hurt someone, so an answer is only useful when it comes from the manuals
and shows the page it came from. A language model writes a fluent answer whether or not
the manuals contain one, and a small local model forgets instructions more easily than
a large hosted one.

How should the system decide when to answer, and how should it tie each statement to
the page that supports it?

## Decision drivers

- Answers come only from the ingested documents, and gaps are admitted instead of
  guessed (FR-006, FR-007, FR-008).
- No answer cites a page that was not retrieved for the question (FR-011, SC-002).
- A question the manuals have nothing to do with costs no model time (FR-006).
- Part numbers and error codes are still found and answered (FR-004).
- Everything runs locally, on the model already served for figure descriptions.
- A correct answer is not lost because the model forgot a citation mark.

## Considered options

1. A relevance gate before the model, a grounded prompt, and citations checked after
   generation.
2. The model decides every time, guided only by its instructions.
3. A structured output that forces a list of sources on every statement.
4. A second model that reranks the passages and scores their relevance.

## Decision outcome

Chosen option: **a relevance gate before the model, a grounded prompt, and citations
checked after generation**.

- Search combines meaning and exact keywords. The model is asked only when a passage is
  close enough in meaning to the question, or contains a code the question names, such
  as `SPL-480`. Otherwise the answer is "not enough information" at once, in the
  language of the question.
- The model receives its rules apart from the passages. Each passage carries a number,
  its document, its pages and its section, and the rules treat the passages and the
  question as data, never as instructions.
- The model marks each statement with the numbers of its passages. Only numbers that
  point to a passage it was given are kept, passages from the same pages become one
  citation, and the citations are renumbered in reading order.
- When the model forgets every mark, each sentence is matched to the passage it repeats,
  by shared words and by meaning, as RAGFlow does. When nothing can be cited, the answer
  is not shown and the response says the documents do not contain enough information.
- The answer shows the figure closest to the cited text on its page.

### Consequences

- Good, because an answer can only cite pages that were retrieved, and every citation
  names the document and the pages.
- Good, because questions unrelated to the manuals are answered in under a tenth of a
  second, without waiting for the model or loading it.
- Good, because the rules live in the application, so another model or provider gets the
  same grounding without changes.
- Bad, because the threshold was set on a small set of questions. A larger reference set
  is planned to tune it.
- Bad, because matching a sentence to a passage by words and meaning shows where a
  statement came from, but cannot prove that the passage supports it.
- Bad, because the system is stricter than the reference projects, which show an
  uncited answer anyway. An answer that cannot be tied to any passage is withheld.

## Annex: technical evidence

### Relevance gate

[ADR 0009](0009-reranked-relevance-gate.md) replaces the cosine threshold below with a
reranker's judgement. The identifier rule is kept.

The fused score of hybrid search (Reciprocal Rank Fusion) depends only on ranks, so
every question has a top hit with the same score, however unrelated it is. A second
Qdrant query with the same question vector, restricted to the fused ids with a
`HasIdCondition` and run with `exact=True`, returns the cosine similarity of each hit.
RAGFlow reads a clean cosine the same way, with a second query filtered by the candidate
ids.

| Questions on the sample manuals | Top cosine similarity |
|---|---|
| Relevant, paraphrased or in another language | 0.648 to 0.821 |
| Hard negatives on similar topics | 0.494, 0.547 |
| Unrelated | 0.268 to 0.300 |
| Identifier question (`SPL-480`) | 0.418 |

The default of 0.60 separates the measured sets. Identifier questions score low on
meaning while keyword search ranks the right passage first, so a passage that holds an
identifier of the question as a whole token passes too. An identifier is a token of at
least three characters with a digit, compared without case or accents.

Queries use Qwen3-Embedding's retrieval instruction, `Instruct: {task}\nQuery:{question}`,
and passages none, as the model card documents. The instruction raised the similarity of
relevant questions (0.669 to 0.761) and lowered it for unrelated ones (0.418 to 0.300).

### Why not the other options

- **The model alone** spends 6 to 13 seconds and the model's availability on every
  question, and FR-006 requires no model call when nothing relevant was retrieved.
- **Structured statements with source ids** always cited, but on 12 questions they were
  30 to 50% slower, turned numbered procedures into prose, cited all eight passages in
  one statement and were cut by the token limit once.
- **A reranker** gives a better calibrated relevance score, and Anthropic reports a 67%
  drop in retrieval failures with one. It is a third model to serve, and the
  specification defers it until the success criteria require it. Qwen3-Reranker-0.6B is
  the candidate.
- **A regular expression that forces a citation mark** during generation worked in one
  measurement. None of the 14 reviewed projects does it, and llama.cpp silently accepts
  any text for a pattern it cannot compile.

### Prompt

- The passages sit in `<source id="n" document="…" pages="…" section="…">` tags, and the
  question in a `<question>` tag after them. Anthropic's and OpenAI's guides recommend
  XML-style tags and the question at the end, and Open WebUI builds its context the same
  way. A closing tag inside a passage is escaped.
- The rules for citation marks and for the answer's language are repeated after the
  question. With eight long passages the model otherwise dropped the marks. OpenAI's
  GPT-4.1 guide recommends instructions at both ends of a long context, and Onyx repeats
  its citation reminder the same way.
- A rule adapted from Onyx asks the model to say when the passages lack the requested
  information instead of answering with related information.
- The output is a JSON object with `answer`, Markdown with `[n]` marks, and
  `not_covered`, what the passages do not answer. llama.cpp enforces it as a grammar,
  and the application validates it again.
- Temperature stays at 0. The model card's sampling for non-thinking use (temperature
  0.7, top_p 0.8, top_k 20, presence_penalty 1.5) brought no gain on 12 questions and
  left one more answerable question unanswered. An answer cut by the token limit is an
  error rather than a partial answer.

### Citations

- Marks are read as `[n]`. The variants `[1, 3]`, `[1-3]`, `[[1]]` and `【1】` are
  accepted first, as Onyx, RAGFlow and Open WebUI accept them.
- A mark whose number is not a supplied passage is removed. This is what keeps every
  citation inside the retrieved content.
- An answer without any mark is split into lines and sentences. Each statement of three
  words or more gets the mark of the passage with the best score, 0.7 for the share of
  its words found in the passage and 0.3 for the cosine of their embeddings, RAGFlow's
  weighting, when that score reaches 0.5. On 43 statements the model did cite, the best
  passage was the cited one in 98% of them. With the cosine alone it was 86 to 88%.
- An answer that only cites passages that do not exist is not attributed, because its
  references were invented.

### Results on the reference machine

Through the API, on the three sample manuals:

| Measurement | Result |
|---|---|
| Answerable questions answered with citations | 12 of 12, one through attribution |
| Unrelated questions | "Not enough information" in under 0.1 s, no model call |
| Request time of answered questions | 9.5 to 21.9 s |
| `SPL-480` | Answered from page 13 of the scanned manual |
| Shunt generator wiring | Figure 4-22 as the primary image |

### Sources

- https://qdrant.tech/documentation/concepts/hybrid-queries/
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://huggingface.co/Qwen/Qwen3.5-9B
- https://www.anthropic.com/news/contextual-retrieval
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide
- https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/prompts/chat_prompts.py
- https://github.com/infiniflow/ragflow/blob/main/internal/service/citation.go
- https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
- Full analysis: `specs/002-grounded-question-answering/research.md`, sections 2 to 7
  and 14
