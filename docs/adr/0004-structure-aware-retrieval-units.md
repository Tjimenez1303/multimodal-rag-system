# 0004. Structure-aware retrieval units

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Search does not return whole documents but smaller pieces of them, called retrieval
units. How those pieces are cut decides whether an answer can quote a complete
procedure, read a whole table, or find a diagram by a label printed inside it. Cutting
every few hundred words, the common default, splits sentences and tables in half and
separates figures from their captions.

How should documents be divided for search?

## Decision drivers

- No unit cuts a sentence or a table in half (FR-010, SC-005).
- Every unit knows its section, pages and related figures (FR-011).
- A diagram can be found by its caption, its labels and its description.
- A table that continues on the next page is found as one table.
- The rules can be tested without the extraction library.

## Considered options

1. The project's own rules, applied to the elements ingestion extracts.
2. Docling's HybridChunker.
3. Fixed-size windows of tokens.

## Decision outcome

Chosen option: **the project's own rules**, which follow the same principles as
Docling's chunkers but work on the project's own elements:

- A unit follows the reading order and ends at every heading, table and figure.
  Paragraphs under the same headings are grouped up to 480 tokens.
- Each unit carries the path of headings above it, its pages, its source elements and
  the figures next to it.
- Each table is one unit, however long.
- Each relevant figure is one unit made of its caption, its labels and its description.
- Two parts of a table on consecutive pages are linked, and form one unit that cites
  both pages.

### Consequences

- Good, because sentences and tables are never cut, and a search for a valve code finds
  the diagram that prints it.
- Good, because the rules are plain code over plain data, tested without any library.
- Bad, because the project maintains its own chunker instead of reusing one.
- Bad, because long tables exceed what the embedding model reads (2,048 tokens), so only
  their beginning counts for search by meaning. Keyword search still sees the whole
  table.

## Annex: technical evidence

### Why not HybridChunker

The domain core must not import Docling (constitution, Principle I). HybridChunker also
drops the labels inside pictures unless a custom serializer enables `traverse_pictures`,
and it does not link table parts across pages. Its rules define ours: peers under the
same headings merge, the heading path is prepended before embedding (`contextualize`),
and the token ceiling is measured on that contextualized text.

### Sentence splitting

A paragraph above the ceiling is split at sentence ends and packed greedily, the regex
fallback LlamaIndex's `SentenceSplitter` uses. A single sentence above the ceiling stays
whole. None of the 2,468 paragraphs in the samples exceeds 480 tokens. The semchunk
library, used by HybridChunker, was rejected because it splits first at the longest
whitespace run and cuts inside long sentences.

### Tokens

Counted with the embedding model's own Hugging Face tokenizer, which matched the counts
of the served model. The largest sample table measures 3,770 tokens, so the dense input
is truncated at 2,048 tokens, the first remedy OpenAI's cookbook gives for long inputs,
while BM25 receives the full text.

### Tables across pages

Docling does not merge split tables (issues #2976 and #2060). The rule follows
Microsoft's cross-page table sample: consecutive pages, the same column count, only page
furniture or captions between the parts, the first part ending in the lower half of its
page and the second starting in the upper half. Repeated header rows are removed from
the joined text. The rule links both parts of the `split_table.pdf` fixture.

### Figures

Logos, icons, stamps, codes, full-page scan images and images repeated on at least 3
pages or 20% of the pages are decorative and never described. Figures under 5% of their
page area are not described but stay as context, the same thresholds Docling's picture
description uses.

### Results on the samples

The FAA chapter produced 309 units, the INSST guide 309 and the scanned TM manual 173.
Three clean runs of the INSST guide produced identical counts.

### Sources

- https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hybrid_chunker.py
- https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/hierarchical_chunker.py
- https://docling-project.github.io/docling/concepts/chunking/
- https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/text/sentence.py
- https://developers.openai.com/cookbook/examples/embedding_long_inputs
- https://github.com/docling-project/docling/issues/2976
- [Azure cross-page table sample](https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/Python(v4.0)/Retrieval_Augmented_Generation_(RAG)_samples/sample_identify_and_merge_cross_page_tables.py)
- Full analysis: `specs/001-async-pdf-ingestion/research.md`, sections 7, 8, 9 and 15
