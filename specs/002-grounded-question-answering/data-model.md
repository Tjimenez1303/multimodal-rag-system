# Data Model: Grounded Question Answering

This feature stores nothing. Questions and answers live only for the duration of a
request (spec, Assumptions). It reads the Document, IngestionJob, ExtractedElement,
ElementRelationship and RetrievalUnit entities of
`specs/001-async-pdf-ingestion/data-model.md` and never writes them. Positions use the
same convention as ingestion: PDF points with a top-left origin.

The types below are frozen dataclasses in `answering/domain.py`. The HTTP schemas in
[contracts/openapi.yaml](contracts/openapi.yaml) mirror them.

## Question

| Field | Type | Rules |
|---|---|---|
| `text` | string | Trimmed. 1 to `MAX_QUESTION_CHARS` (2,000) characters, else `InvalidQuestionError` (FR-002) |
| `document_ids` | tuple of UUID or `None` | `None` means every completed document. When set, 1 to `MAX_FILTER_DOCUMENTS` (20) distinct ids. Unknown ids raise `UnknownDocumentsError` and ids whose latest job is not completed raise `DocumentsNotReadyError`, both naming the ids (FR-020) |

## Answer

| Field | Type | Notes |
|---|---|---|
| `status` | `AnswerStatus` | `answered` or `not_enough_information` (FR-009) |
| `reason` | `NotEnoughReason` or `None` | Set only when `status` is `not_enough_information` |
| `text` | string | Markdown with `[n]` markers when answered (FR-010, FR-027). Otherwise a message in the question's language |
| `not_covered` | string or `None` | What the sources do not answer, when the answer is partial (FR-008) |
| `citations` | tuple of `Citation` | Empty when not answered |
| `sources` | tuple of `RetrievedSource` | Every unit supplied to the model, in rank order, empty when the model was not asked (FR-012) |
| `primary_image` | `AnswerImage` or `None` | At most one (FR-015) |
| `related_images` | tuple of `AnswerImage` | Ordered by relevance, never containing the primary image (FR-016) |

### AnswerStatus

| Value | Meaning |
|---|---|
| `answered` | At least one valid citation remains |
| `not_enough_information` | The documents do not support an answer |

### NotEnoughReason

| Value | When | Model asked |
|---|---|---|
| `no_searchable_documents` | The search returned no unit, because no document in scope completed ingestion | No |
| `no_relevant_content` | No retrieved unit passed the relevance gate | No |
| `not_answered_by_sources` | The model returned an empty answer | Yes |
| `no_valid_citations` | Every marker in the model's answer pointed outside the supplied sources | Yes |

When the model was asked, `text` is its `not_covered` sentence if it wrote one. Otherwise,
and whenever the model was not asked, `text` is the fixed message for the reason in the
question's language.

## Citation

| Field | Type | Notes |
|---|---|---|
| `number` | integer ≥ 1 | Matches the `[n]` markers in `Answer.text`, numbered in order of first appearance |
| `document_id` | UUID | |
| `document_name` | string | File name of the document |
| `pages` | tuple of integers | Ascending. Every page of the cited units, such as both pages of a continued table |
| `unit_ids` | tuple of UUID | Supplied units merged into this citation because they share document and pages |

Invariants: every number in the text has a citation, every citation is referenced at
least once, and every unit id belongs to `Answer.sources` (FR-011).

## RetrievedSource

| Field | Type | Notes |
|---|---|---|
| `unit_id` | UUID | Retrieval unit id |
| `rank` | integer ≥ 1 | Position in the fused ranking |
| `similarity` | float | Dense cosine similarity to the question |
| `document_id`, `document_name` | UUID, string | |
| `section` | tuple of strings | Heading path, outermost first |
| `pages` | tuple of integers | |
| `content_type` | `text`, `table` or `figure` | The unit type |
| `excerpt` | string | First 300 characters of the unit text |
| `citation_number` | integer or `None` | Citation that cites this unit, if any |
| `low_confidence_text` | boolean | An element was recognized below `LOW_CONFIDENCE_THRESHOLD` (FR-013) |
| `generated_description` | boolean | Figure unit whose text includes a model description (FR-014) |
| `unverified_identifiers` | tuple of strings | Carried from the figure element (FR-014) |
| `tables` | tuple of `TableContent` | One per table element of a table unit, else empty (FR-018) |

`cited` in the HTTP body is `citation_number is not None`.

## TableContent

| Field | Type | Notes |
|---|---|---|
| `page` | integer | Page of this table part |
| `rows` | tuple of tuples of strings | Cell text, header row first, as ingestion stored it |

## AnswerImage

| Field | Type | Notes |
|---|---|---|
| `element_id` | UUID | Image element id |
| `document_id`, `document_name` | UUID, string | |
| `page` | integer | |
| `bbox` | `BoundingBox` | PDF points, top-left origin |
| `caption` | string or `None` | Text of the element linked by `caption_of` |
| `unit_id` | UUID | Cited unit that brought the image |
| `url` | string | Path of the existing image route, built by the HTTP adapter |

Selection rules are in [research.md](research.md), section 7. Decorative images and images
without a stored crop are never returned (FR-017).

## Internal values

| Type | Fields | Use |
|---|---|---|
| `GroundedPrompt` | `system`, `user` | Built by `answering/prompting.py`, sent by the `AnswerGenerator` adapter |
| `GeneratedAnswer` | `text`, `not_covered` | Validated output of the answer model |

## Ports

New ports, in `answering/ports.py`:

| Port | Methods | Production adapter | Test fake |
|---|---|---|---|
| `AnswerGenerator` | `generate(prompt) -> GeneratedAnswer` | `adapters/openai_compatible/answerer.py` | `FakeAnswerGenerator` with scripted answers and failures |
| `AnswerSlots` | `admit()` async context manager, raises `AnsweringBusyError` | `adapters/concurrency/anyio_slots.py` | `FakeAnswerSlots` with a configurable capacity |
| `LanguageIdentifier` | `identify(text, *, candidates) -> str` | `adapters/language/py3langid_identifier.py` | `FakeLanguageIdentifier` |

Changes to ingestion ports, each with its adapter and fake updated:

| Port | Change |
|---|---|
| `Embedder` | Adds `embed_query(text) -> list[float]` |
| `VectorIndex` | `search_hybrid` returns hits that also carry `similarity`. A missing collection returns no hits |
| `ElementRepository` | Adds `get_many(element_ids) -> tuple[ExtractedElement, ...]` |
| `DocumentRepository` | Adds `get_many(document_ids) -> tuple[Document, ...]`, which skips unknown ids so the caller can name them |

## Errors

New errors, in `answering/errors.py`, plus the `CapacityError` family in
`shared/errors.py`. Codes, families and HTTP statuses are in [research.md](research.md),
section 11.

## Validation rules from the spec

| Rule | Source | Where enforced |
|---|---|---|
| Question length and emptiness | FR-002 | `Question` construction |
| Only completed documents are searched | FR-003 | `visible` filter in `search_hybrid` (ingestion) and the restriction check |
| No model call below the gate | FR-006 | `answering/relevance.py`, checked before generation |
| Citations only to supplied units | FR-011, SC-002 | `answering/citations.py` |
| Every citation referenced, markers renumbered | FR-010 | `answering/citations.py` |
| Decorative images never returned | FR-017 | `answering/images.py` |
| Deadline covers waiting | FR-022, FR-028 | `AnswerQuestion` with `asyncio.timeout` around admission and work |
