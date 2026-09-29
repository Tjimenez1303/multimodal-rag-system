# Data Model: Asynchronous PDF Ingestion

Entities are defined in the domain core as plain dataclasses and enums with no framework
imports. PostgreSQL stores documents, jobs, elements and relationships. Qdrant stores the
retrieval units. The blob volume stores the original PDFs and the figure crops.

Coordinates are PDF points (1/72 inch) with a top-left origin on every page. The extraction
adapter converts Docling's bottom-left boxes before they reach the domain.

## Document

An uploaded PDF, identified by the fingerprint of its bytes.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Generated on registration |
| `sha256` | 64 hex chars | Unique. Computed while the upload is stored (FR-016) |
| `file_name` | text | Original name as uploaded, at most 255 characters |
| `size_bytes` | integer | At most the configured size limit (200 MB by default) |
| `page_count` | integer, nullable | Read at upload. Null only for encrypted files, which fail later |
| `blob_key` | text | `documents/{sha256}.pdf` |
| `created_at` | timestamp with time zone | Set on registration |

A document has many ingestion jobs. Its latest job decides the status shown in the library.
The upload registers the document and then enqueues its job, so a document has no job
for a moment, or until the same content is uploaded again when that enqueue failed. The
library shows such a document with no latest job.

## IngestionJob

One ingestion request for a document, run in at most `max_attempts` attempts.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Returned to the client as `job_id` |
| `document_id` | UUID | Foreign key to Document |
| `status` | enum `JobStatus` | See the state machine below |
| `stage` | enum `JobStage`, nullable | Current stage while processing |
| `pages_total` | integer, nullable | Known once extraction starts |
| `pages_done` | integer | 0 to `pages_total` |
| `attempt` | integer | 0 before the first claim. Incremented on every claim |
| `max_attempts` | integer | From configuration, 3 by default (FR-025) |
| `lease_token` | UUID, nullable | Fencing token of the current attempt |
| `lease_expires_at` | timestamp, nullable | Renewed by the worker heartbeat |
| `worker_id` | text, nullable | Host and process of the current holder, for diagnostics |
| `correlation_id` | text | Request id of the upload that created the job |
| `failure_code` | enum `FailureCode`, nullable | Set only when failed |
| `failure_reason` | text, nullable | Human-readable, never contains document content |
| `summary` | JSON, nullable | `JobSummary`, set only when completed |
| `created_at`, `started_at`, `finished_at`, `updated_at` | timestamps | `started_at` is set on the first claim |

### JobStatus state machine

```text
pending ──claim──▶ processing ──success──▶ completed
                     │  ▲
                     │  └── lease expired and attempt < max_attempts (reclaimed, stays processing)
                     │
                     ├── non-retryable error ──▶ failed
                     └── lease expired and attempt = max_attempts ──▶ failed (interrupted repeatedly)
```

- Transitions only move forward. `completed` and `failed` are terminal (FR-004).
- A reclaim increments `attempt` and issues a new `lease_token`. Any write that carries an
  old token affects zero rows, and the stale worker aborts (fencing).
- A document whose latest job failed may get a new job when the same content is uploaded
  again (FR-016).

### JobStage

`extracting`, `describing_figures`, `building_units`, `embedding`, `indexing`,
`finalizing`.

### FailureCode

| Code | Cause | Retried |
|---|---|---|
| `encrypted_document` | Password-protected PDF | No |
| `corrupt_document` | Parser cannot read the file | No |
| `no_extractable_text` | No text from the text layer or from recognition on any page | No |
| `provider_unavailable` | Embedding or index service unavailable after the retry budget | No (the budget already ran) |
| `interrupted_repeatedly` | Lease expired on the last allowed attempt | No |
| `internal_error` | Data inconsistency or unexpected error | No |

Figure description failures never fail a job (FR-027).

### JobSummary

`pages`, `text_elements`, `tables`, `table_chains`, `images`, `figures_described`,
`figures_skipped`, `figures_not_described`, `retrieval_units`, `recognized_pages`.

## ExtractedElement

A typed piece of content from one page.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID | Deterministic: `uuid5(ID_NAMESPACE, "element:{sha256}:{element_key}")`, so re-processing yields the same ids. `ID_NAMESPACE` is a fixed random UUID (RFC 9562 section 6.6) |
| `document_id` | UUID | Foreign key |
| `kind` | enum `heading`, `paragraph`, `list_item`, `caption`, `table`, `image`, `page_furniture` | `page_furniture` covers headers, footers and page numbers |
| `page` | integer | 1-based |
| `bbox` | `BoundingBox` | Required on every element (FR-008) |
| `reading_order` | integer | Order within the document |
| `heading_level` | integer, nullable | Only for headings |
| `text` | text, nullable | Text content, or the serialized table for tables |
| `table` | JSON, nullable | Rows and columns with cell text, only for tables |
| `origin` | enum `text_layer`, `recognized` | FR-023. Images use `text_layer` |
| `confidence` | float 0–1, nullable | Only when `origin = recognized` |
| `image_key` | text, nullable | Blob key of the crop, only for images |
| `image_class` | text, nullable | Classifier label (diagram, photo, logo…) |
| `labels` | list of text | Text found inside the image. Images only (FR-024) |
| `description` | text, nullable | Generated description. Images only (FR-026) |
| `description_status` | enum `described`, `skipped`, `not_described`, nullable | Images only (FR-027) |
| `unverified_identifiers` | list of text | Identifiers in the description missing from labels and caption (FR-028) |
| `is_decorative` | boolean | Logos, icons, signatures, stamps, codes, full-page scan images or images repeated on at least 3 pages or on at least 20% of the pages (FR-014). Decorative images are `skipped` for description |

### BoundingBox (value object)

`left`, `top`, `right`, `bottom` as floats in PDF points, with `origin = top_left`.
Validation requires `left < right`, `top < bottom`, and every value within the page size.

## ElementRelationship

| Field | Type | Rules |
|---|---|---|
| `source_id` | UUID | Element |
| `target_id` | UUID | Element |
| `kind` | enum `caption_of`, `title_of`, `describes`, `near`, `continues` | `continues` links part N+1 of a table to part N (FR-009) |
| `score` | float, nullable | Proximity or match strength, for `near` and `continues` |

Rules:

- `caption_of` links a caption to its image and `title_of` a caption to its table. Docling
  assigns most captions, and a domain rule links the captions it leaves alone.
- `continues` links part N+1 of a table to part N. Both are on consecutive pages with the
  same column count. The earlier part ends in the lower half of its page, the later part
  starts in the upper half of its page, and no text other than page furniture and the
  captions of either part lies between them in reading order.
- `near` links the closest paragraph or list item to an image: same column, within
  `NEAR_TEXT_MAX_POINTS`, on the image's page or on the next page when its caption
  continues there. The score is `1 - gap / NEAR_TEXT_MAX_POINTS`.
- `describes` is reserved and not produced by this feature.

The elements endpoint returns, for each element, every relationship that touches it as
an edge `{source_id, target_id, kind}`, the edge shape of JSON Graph Format v2, so an
image shows its caption and nearby text.

## RetrievalUnit (stored in Qdrant)

A structurally coherent group of content prepared for search.

| Payload field | Type | Rules |
|---|---|---|
| point id | UUID | `uuid5(ID_NAMESPACE, "unit:{sha256}:{unit_key}")` |
| `document_id` | UUID | Indexed |
| `unit_type` | `text`, `table`, `figure` | Indexed |
| `text` | text | Unit content for display. Figures combine caption, labels and description. Table chains join their parts without repeated headers. Both vectors receive the heading path and this text joined by newlines, and the dense side is truncated to `EMBEDDER_MAX_INPUT_TOKENS` |
| `heading_path` | list of text | Section headings in scope |
| `pages` | list of integers | Indexed. A table chain lists every page it spans (FR-011) |
| `element_ids` | list of UUID | Source elements |
| `boxes` | list of `{page, left, top, right, bottom}` | For highlighting in later features |
| `figure_ids` | list of UUID | Related images for text and table units |
| `image_key` | text, nullable | Figure units only |
| `visible` | boolean | Indexed. `false` until the job completes (FR-018) |

Vectors: `dense` (1024 dimensions, cosine) and `bm25` (sparse, IDF modifier, computed by
the server).

## Validation rules from the spec

| Rule | Where it is enforced |
|---|---|
| File is a PDF by content and within the size and page limits (FR-002) | API, through `PdfInspector` before any job exists |
| One document per `sha256`, including concurrent uploads (FR-016) | `UNIQUE(sha256)` with `ON CONFLICT DO NOTHING` |
| Forward-only job states (FR-004) | Domain `IngestionJob` transition methods. Every SQL write first locks the job row by id and current lease token, then saves the transition the domain computed |
| At most `max_attempts` attempts, never two workers at once (FR-025) | Claim query, lease token and fencing on every write |
| Every element has a page and a box (FR-008, SC-004) | Domain constructor. The adapter raises `DataInconsistencyError` otherwise |
| No duplicates on re-processing (FR-015, SC-008) | Deterministic element and point ids. Elements are replaced in one fenced transaction |
| Nothing searchable from a failed job (FR-018) | `visible=false` until completion, and points deleted by `document_id` on failure |
