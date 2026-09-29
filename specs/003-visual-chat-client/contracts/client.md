# Client Contract: Visual Chat Client

What the `frontend` service exposes and how the client uses the service's HTTP
interface. The service operations themselves are defined in the OpenAPI contracts of
features 001 and 002 and in [openapi.yaml](openapi.yaml).

## 1. Routes served by the frontend service

| Route | Served by | Content |
|---|---|---|
| `/` and any path without a file | nginx, `try_files` | `index.html` with this response's style nonce, `Cache-Control: no-store` |
| `/assets/*` | nginx | Hashed build assets, `Cache-Control: public, max-age=31536000, immutable` |
| `/config.json` | nginx, rendered from the environment at start | Runtime configuration below, `Cache-Control: no-store` |
| `/healthz` | nginx | `200 ok`, used by the Compose healthcheck |
| `/api/*` | nginx proxy to `http://api:8000` | The service API, unchanged. Uploads are streamed, with no nginx body size limit |
| `/health/*`, `/docs`, `/openapi.json` | not proxied | Only reachable on the API's own port |

Every response carries the security headers in research section 4.

### Runtime configuration (`/config.json`)

```json
{
  "answerWaitSeconds": 105,
  "maxFilterDocuments": 20,
  "statusPollSeconds": 2
}
```

| Field | Type | Constraint |
|---|---|---|
| `answerWaitSeconds` | number | Greater than 0. Set above the service's `ANSWER_DEADLINE_SECONDS` |
| `maxFilterDocuments` | integer | At least 1. Equal to the service's `MAX_FILTER_DOCUMENTS` |
| `statusPollSeconds` | number | Greater than 0 |

## 2. Request conventions

- Every request carries `X-Request-ID` with a fresh `crypto.randomUUID()` value. The same
  value is the failure reference shown to the user.
- Questions are sent with `POST /api/v1/questions` and an `AbortSignal`. The signal fires
  when the user presses stop or when `answerWaitSeconds` elapses. At most one question
  request is open at a time.
- `document_ids` is omitted when the selection is empty and holds the selected ids
  otherwise.
- Uploads are sent with `POST /api/v1/documents` as `multipart/form-data`, field `file`,
  and fail after 60 s without transfer progress.
- Every other call times out after 10 s (`SERVICE_CALL_TIMEOUT_SECONDS`).
- Image sources are the relative paths the service returns. Page images use the path of
  `getDocumentPageImage`.

## 3. Failure messages

The client shows these messages under the failed turn or upload, followed by
"Reference: {X-Request-ID}". "detail" means the problem's `detail` field, which the
service writes in plain English and which names the offending documents or limits.

### Questions

| Status and code | Kind | Message | Action |
|---|---|---|---|
| 400 `invalid_question` | `invalid_question` | detail | Question text returned to the input, no retry |
| 400 `unknown_documents`, 409 `documents_not_ready` | `restriction` | detail | "Edit and ask again": question returned to the input, selection pruned (FR-041) |
| 400 `invalid_request` or another 4xx | `rejected` | "The question could not be sent." followed by detail when present | Retry |
| 503 `answering_busy` | `busy` | "The system is busy answering other questions. You can retry in {Retry-After} seconds." | Retry |
| 503 `answer_model_unavailable` | `answer_model` | "The answer model is not responding." | Retry |
| 504 `answer_model_timeout` | `answer_model` | "The answer model took too long to answer." | Retry |
| 502 `answer_model_invalid_response` | `answer_model` | "The answer model could not produce an answer." | Retry |
| 503 `search_unavailable` | `search` | "Search is not available right now." | Retry |
| 504 `search_timeout` | `search` | "Search took too long to respond." | Retry |
| 504 `answer_deadline_exceeded` | `deadline` | "The question took longer than the time limit." | Retry |
| Any other 5xx | `service` | "Something went wrong on the service." | Retry |
| No response (`unreachable`) | `unreachable` | "The service could not be reached." | Retry |
| No response within `answerWaitSeconds` (`timed_out`) | `timed_out` | "The service did not answer in time." | Retry |
| Body that does not match the contract (`unreadable`) | `unreadable` | "The service sent a response that could not be read." | Retry |

### Uploads

| Status and code | State | Message | Action |
|---|---|---|---|
| Client pre-check (not a PDF) | `rejected` | "Only PDF files can be uploaded." | None |
| 400, 413, 415 or 422 (for example `file_too_large`, `page_limit_exceeded`, `unsupported_media_type`) | `rejected` | detail | None |
| Any 5xx | `failed` | "The file could not be stored." | Upload again |
| No response | `failed` | "The service could not be reached." | Upload again |

### Document deletion

Shown inside the delete confirmation, which stays open so the user can try again or
cancel (FR-049).

| Status and code | Message | Action |
|---|---|---|
| 204 | None | The dialog closes and the document leaves the list |
| 404 `document_not_found` | None. It was already deleted elsewhere | Same as 204 |
| 409 `ingestion_in_progress` | "This document is being processed. It can be deleted once processing ends." | Cancel |
| Another 4xx | "The document could not be deleted." followed by detail when present | Delete again |
| Any 5xx | "The document could not be deleted." | Delete again |
| No response (`unreachable`) | "The service could not be reached." | Delete again |
| No response within 10 s (`timed_out`) | "The service did not answer in time." | Delete again |
| Body that does not match the contract (`unreadable`) | "The service sent a response that could not be read." | Delete again |

### Other calls

| Call | Failure | Behavior |
|---|---|---|
| `/config.json`, `listDocuments` | Any, including the 10 s timeout | Connection notice (FR-030), retried with backoff until it succeeds |
| `getDocument` while following a job | Any | Kept at the last known status and retried on the next interval, with the connection notice while failing |
| Figure or page image | Load error | "Image unavailable" or "Page unavailable", keeping the document name, page and caption (spec edge cases) |
