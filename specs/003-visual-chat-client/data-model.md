# Data Model: Visual Chat Client

The client owns only browser state (sections 1 and 3). Service data is read through the
contracts of features 001, 002 and 003 and is never modified by the client (section 2).
The one backend addition, page images, is in section 4. Research references point to
[research.md](research.md).

## 1. Browser state

### 1.1 Conversation

The ordered turns of the current tab, persisted in `sessionStorage` (research section 8).

| Field | Type | Rules |
|---|---|---|
| `version` | `1` | Storage schema version. A stored value with another version is discarded, and the tab starts empty |
| `turns` | `Turn[]` | In submission order. Cleared only by "New conversation" after confirmation (FR-004) |

- **Storage key**: `multimodal-rag.conversation.v1`.
- **Writes**: after every state change. A `QuotaExceededError` keeps the state in memory
  and raises the "will not survive a reload" notice.
- **Reads**: once at start. Turns restored as `waiting` become `stopped` with
  `stopReason: "reload"`.

### 1.2 Turn

| Field | Type | Rules |
|---|---|---|
| `id` | UUID string | Created in the browser, stable across retries |
| `question` | string | Trimmed, at least one character. The service enforces the maximum length |
| `restriction` | `DocumentRef[]` | Snapshot of the selection when the turn was submitted. Empty means all documents. Reused unchanged on retry (FR-028, FR-040) |
| `state` | `TurnState` | See the transitions below |
| `requestId` | string or `null` | `X-Request-ID` of the latest attempt, `null` while held |
| `response` | `Answer` or `null` | The service's body exactly as returned (FR-022). Set only in `answered` and `no_information` |
| `failure` | `TurnFailure` or `null` | Set only in `failed` |
| `stopReason` | `"user"`, `"reload"` or `null` | Set only in `stopped` |

`DocumentRef` is `{ id: UUID, fileName: string }`. The name is kept so a turn can show
its restriction after the document leaves the library.

**Turn states and transitions**:

| From | Event | To |
|---|---|---|
| (new) | Submitted while another turn is `waiting` or `held` | `held` |
| (new) | Submitted with no turn `waiting` or `held` | `waiting` |
| `held` | Queue reaches it (no turn `waiting`) | `waiting` |
| `waiting` | 200 with `status: answered` | `answered` |
| `waiting` | 200 with `status: not_enough_information` | `no_information` |
| `waiting` | Problem response, network error, wait limit reached or unreadable body | `failed` |
| `waiting` | Stop button | `stopped` (`user`) |
| `waiting` | Page reload | `stopped` (`reload`) |
| `failed` or `stopped` | Retry | `held`, sent when the queue reaches it |

**Rules**:

- At most one turn is `waiting` at any time (FR-006).
- `held` turns are sent in the order they were submitted or retried.
- A turn that fails with 400 `invalid_question` puts its question text back into the input
  (FR-029). The turn stays `failed` without a retry action, since the same text would be
  rejected again.

### 1.3 TurnFailure

| Field | Type | Rules |
|---|---|---|
| `kind` | `FailureKind` | One of the kinds in [contracts/client.md](contracts/client.md), section 3 |
| `message` | string | Plain English, from the table in `contracts/client.md` or from the problem `detail` where that table says so |
| `retryable` | boolean | From the same table |
| `retryAfterSeconds` | number or `null` | From `Retry-After`, only for `answering_busy` |
| `reference` | string | The attempt's `X-Request-ID` (FR-025) |

### 1.4 Document selection

| Field | Type | Rules |
|---|---|---|
| `documents` | `DocumentRef[]` | Only documents whose latest job is `completed`. At most `maxFilterDocuments`. Empty means all documents |

- **Storage key**: `multimodal-rag.selection.v1` in `sessionStorage`.
- **Pruning**: whenever the library refreshes, a selected document that is missing or not
  `completed` is removed, and a notice names it (FR-041).

### 1.5 Panel state

`{ collapsed: boolean }` under `multimodal-rag.panel.v1` in `sessionStorage`. The panel
starts open (FR-031).

### 1.6 Tracked upload

In memory only. An upload in progress cannot survive a reload, and once accepted it is
followed through the library (FR-035).

| Field | Type | Rules |
|---|---|---|
| `id` | UUID string | Created in the browser |
| `fileName`, `sizeBytes` | string, number | From the chosen file |
| `state` | `"sending"`, `"accepted"`, `"rejected"` or `"failed"` | `rejected` is a 4xx problem from the service or the client's PDF pre-check. `failed` covers network and 5xx errors |
| `sentFraction` | number from 0 to 1 | Transfer progress while `sending` |
| `requestId` | string | `X-Request-ID` of the upload |
| `documentId`, `alreadyIngested` | UUID and boolean, or `null` | From `UploadAccepted` once accepted |
| `failure` | `TurnFailure` or `null` | The service's `detail` for rejections (FR-036), the fixed message otherwise |

An accepted upload leaves the tracked list once its document shows in the library.

## 2. Service data the client reads

Shapes come from the generated client (research section 5), which is built from these
contracts:

- `specs/001-async-pdf-ingestion/contracts/openapi.yaml`
- `specs/002-grounded-question-answering/contracts/openapi.yaml`
- `specs/003-visual-chat-client/contracts/openapi.yaml`

### 2.1 Displayed from an Answer (002)

| Answer field | Displayed as | Requirement |
|---|---|---|
| `status`, `reason` | Answer or no-information state, with guidance per `reason` | FR-021 |
| `answer` | Rendered Markdown, with `[n]` markers linked to citations | FR-008, FR-009, FR-011 |
| `not_covered` | Labeled note under the answer text | FR-020 |
| `citations[]` | Numbered source lines | FR-010 |
| `sources[]` with `cited: true` | Details of each source line: section, excerpt, table rows, flags | FR-012, FR-013 |
| `sources[]` with `cited: false` | "Other retrieved passages", collapsed | FR-014 |
| `primary_image` | Image column, first position | FR-015 |
| `related_images[]` | Image column, secondary group under the primary image | FR-017 |

**Rules for display**:

- **Source label**: "Source: {document_name}, page {n}" for one page. For several pages,
  "pages" followed by runs of consecutive pages joined with an en dash and separated by
  commas, for example "pages 12–13" or "pages 3–4, 9". The pages are those of the
  citation, in ascending order.
- **Source details**: a citation's details come from the sources listed in its
  `unit_ids`, in rank order.
- **Guidance for `not_enough_information`**:

  | Reason | Guidance |
  |---|---|
  | `no_searchable_documents` | Upload a manual, with a control that opens the upload |
  | Any reason, turn restricted | "Ask across all documents", which submits the same question with an empty restriction |
  | Any other case | Rephrase the question |

- **Order**: the client never reorders citations, sources or images (FR-022).

### 2.2 Displayed from a Document and its Job (001)

| Field | Displayed as |
|---|---|
| `file_name` | Document name in the list, the selection and restrictions |
| `latest_job.status` | Pending, Processing, Ready (`completed`) or Failed |
| `latest_job.stage` | Plain words: `extracting` "Reading pages", `describing_figures` "Describing figures", `building_units` "Organizing content", `embedding` "Preparing search", `indexing` "Indexing", `finalizing` "Finishing" |
| `pages_done`, `pages_total` | "{done} of {total} pages" while processing |
| `attempt`, `max_attempts` | "Retrying ({attempt} of {max_attempts})" when `attempt > 1` and not finished |
| `summary` | "{pages} pages, {tables} tables, {images} images" when ready |
| `failure_reason` | Readable reason when failed |
| `latest_job: null` | Pending |

### 2.3 Image references

`AnswerImage.url` and element image URLs are same-origin paths, used as the `src` of an
`<img>` as returned. Page images are requested as
`/api/v1/documents/{document_id}/pages/{page}/image` (section 4).

### 2.4 ServiceFailure

The typed result of any failed call, before it becomes a `TurnFailure`:

| Variant | Fields | Produced when |
|---|---|---|
| `problem` | `status`, `code`, `detail`, `requestId`, `retryAfterSeconds` | Response with `application/problem+json` |
| `unreachable` | `requestId` | The request failed before any response (network error, API down behind nginx answering 502 or 504 without a problem body) |
| `timed_out` | `requestId` | No response within `answerWaitSeconds` for a question, or within `SERVICE_CALL_TIMEOUT_SECONDS` (10 s) for any other call except uploads |
| `unreadable` | `requestId` | A success status whose body fails the generated zod validation of the contract |

## 3. Runtime configuration

`GET /config.json`, answered by nginx from a JSON body rendered from the environment at container start
(research section 11). Its schema is in [contracts/client.md](contracts/client.md),
section 1.

| Field | Type | Source variable | Default |
|---|---|---|---|
| `answerWaitSeconds` | number | `ANSWER_WAIT_SECONDS` | 105 |
| `maxFilterDocuments` | integer | `MAX_FILTER_DOCUMENTS` | 20 |
| `statusPollSeconds` | number | `STATUS_POLL_SECONDS` | 2 |

The client validates the file on load and refuses to start with a missing or
non-positive value, showing the connection notice instead (FR-030).

## 4. Backend additions

### 4.1 Page image blob

- **Key**: `pages/{document_id}/{page_number}.png`, built by
  `ExtractedElement.page_image_key_for(document_id=..., page_number=...)` next to the
  existing `image_key_for`.
- **Content**: PNG of the whole page at 144 dpi, as rendered by Docling during
  extraction.
- **Lifecycle**: written during the extraction stage and overwritten when a job is
  retried. A document has page images for pages 1 to `page_count` once its job is
  `completed`.

### 4.2 ExtractionBatch

New field `page_images: dict[int, bytes]`, with the PNG bytes of each page of the batch
keyed by 1-based page number and defaulting to empty. `DoclingExtractor` fills it. The
fake extractor fills it with a tiny PNG per page.

### 4.3 GetPageImage use case

`GetPageImage(documents, jobs, blobs)` in `ingestion/use_cases/library.py`:

| Step | Failure | Error | HTTP |
|---|---|---|---|
| Load the document | Unknown id | `DocumentNotFoundError` | 404 `document_not_found` |
| Check the latest job | Not `completed` | `IngestionNotCompletedError` | 409 `ingestion_not_completed` |
| Check the page number | Outside 1 to `page_count` | `PageNotFoundError` (new, a `NotFoundError`) | 404 `page_not_found` |
| Read the blob | Missing | `DataInconsistencyError` | 500 `data_inconsistency` |

It returns the PNG bytes. The route answers `image/png`.
