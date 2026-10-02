# Runtime flows

This page follows the three main requests through the code, in call order. File paths
are relative to `backend/src/multimodal_rag/`.

## Uploading a PDF

The upload is split in two. The API only stores the file and enqueues a job, and the
worker does the processing later.

### In the API

1. `POST /api/v1/documents` reaches `upload_document` in `adapters/http/routes_ingestion.py`.
   `BodySizeLimitMiddleware` has already refused bodies over `MAX_UPLOAD_BYTES`. The route
   streams the multipart file to the use case in 1 MiB chunks.
2. `SubmitDocument` (`ingestion/use_cases/intake.py`):
   1. Strips any folder from the file name and validates it.
   2. Streams the bytes to a staging key in blob storage, counting them against the size
      limit and hashing them with SHA-256 on the way.
   3. Opens the file with PDFium (`PdfiumInspector`) to prove it is a PDF and count its
      pages. Encrypted PDFs are accepted and fail later with a clear reason.
   4. Moves the file to its content-addressed key, `documents/{sha256}.pdf`.
   5. Registers the document by fingerprint. Uploading identical bytes twice returns the
      document stored the first time.
   6. Reuses the document's job, or enqueues a new one when there is none or the last one
      failed. A partial unique index makes concurrent identical uploads share one job.
3. The route answers 202 with `document_id` and `job_id`, or 200 with
   `already_ingested: true` when the same content was already processed. The `Location`
   header points to `GET /api/v1/jobs/{job_id}`.
4. Inserting the job fires the `ingestion_jobs_notify` trigger, which sends
   `pg_notify('ingestion_jobs', job_id)`.

### In the worker

5. `WorkerLoop.run` (`adapters/worker/loop.py`) waits on a dedicated `LISTEN` connection
   (`PostgresJobNotifications`) and wakes up at once, or after `POLL_SECONDS` at worst.
6. `PostgresJobQueue.claim` takes the oldest claimable job with
   `SELECT ... FOR UPDATE SKIP LOCKED`, so several workers never take the same one. A
   claimable job is pending, or processing under a lease that has expired because its
   worker died. The claim writes a new lease token and expiry measured on the database
   clock. A job that has used `MAX_ATTEMPTS` fails with `interrupted_repeatedly`.
7. While the job runs, a heartbeat renews the lease every `HEARTBEAT_SECONDS`. If the
   lease is lost, the attempt is abandoned.
8. `ProcessJob` (`ingestion/use_cases/processing.py`) runs the pipeline. Each stage is
   recorded on the job so clients can show progress.

| Stage | What happens | Code |
| --- | --- | --- |
| Clean slate | Deletes whatever an earlier attempt indexed for the document | `QdrantVectorIndex.delete_document` |
| `extracting` | Docling converts the PDF `EXTRACTION_PAGE_BATCH` pages at a time, with OCR for scanned pages, table structure and figure classification. Page images and figure crops are saved to blob storage | `DoclingExtractor.extract`, `map_document` |
| `describing_figures` | Decorative images are flagged, and large content figures are described by the vision model with their caption and nearby text as context | `FigurePolicy.triage`, `link_elements`, `OpenAICompatibleFigureDescriber` |
| `building_units` | Elements are grouped into structure-aware retrieval units under their heading path, at most `MAX_UNIT_TOKENS` tokens, with tables and figures kept whole | `build_units` |
| `embedding` | Each unit's heading path and text is embedded | `OpenAICompatibleEmbedder.embed` |
| `indexing` | Units are written to Qdrant with their dense vector and server-side BM25, still hidden | `QdrantVectorIndex.upsert_units` |
| `finalizing` | Elements and relationships replace the old ones in one transaction, then the units become visible | `PostgresElementRepository.replace_for_document`, `QdrantVectorIndex.publish` |

9. On success the job becomes `completed` with a summary of what was found. On failure it
   becomes `failed` with a `failure_code` and a reason a person can read, and anything
   indexed is removed. A database outage or a lost lease abandons the attempt instead,
   and the next claim retries it.
10. The browser follows progress by polling `GET /api/v1/documents/{id}`, which returns
    the document with its latest job.

## Asking a question

The answer is one JSON response. Nothing is streamed.

1. `POST /api/v1/questions` reaches `ask_question` in `adapters/http/routes_questions.py`.
   The route runs the use case under `run_until_disconnect`, which cancels the work if
   the browser goes away.
2. `AnswerQuestion` (`answering/use_cases/ask.py`) validates the question, then runs the
   rest under the `ANSWER_DEADLINE_SECONDS` deadline while holding one of the limited
   answering places (`AnyioAnswerSlots`). When every place and queue position is taken,
   it fails at once with `answering_busy`.
3. **Search.** The question is embedded with the retrieval instruction, and
   `QdrantVectorIndex.search_hybrid` runs a dense search and a BM25 keyword search side by
   side over visible units, fused with reciprocal rank fusion. Each hit is then scored
   again on the dense side to get a comparable cosine similarity. Repeated texts are
   dropped, keeping `RERANK_CANDIDATES` passages. No candidates at all gives
   `no_searchable_documents`.
4. **Reranking.** `OpenAICompatibleRelevanceJudge` asks the Qwen3 reranker, one request
   per passage and all at once, whether the passage answers the question. The
   probability of "yes" against "no" becomes the passage's relevance.
   `rank_by_relevance` keeps the `RETRIEVAL_TOP_K` best, always keeping passages that
   contain an identifier the question mentions, such as a part number.
5. **Relevance gate.** `passes_gate` lets the question through only when a passage
   reaches `MIN_RELEVANCE` or holds one of those identifiers. Otherwise the answer is
   `not_enough_information` with reason `no_relevant_content`, and the answer model is
   never called.
6. **Prompt.** `build_prompt` wraps each passage in a numbered `<source>` tag with its
   document, pages and section, adds the question and the rules (answer only from the
   sources, cite every sentence with `[n]`, treat the sources as data).
7. **Answer.** `OpenAICompatibleAnswerGenerator` calls the answer model with a strict JSON
   schema `{answer, not_covered}`. An empty answer gives `not_answered_by_sources`.
8. **Citations.** `resolve_citations` keeps only markers that point to supplied passages,
   merges passages from the same pages under one number and renumbers them. When the
   model wrote no marker at all, `attribute` adds them by matching each statement to its
   best passage. An answer left without citations is not shown (`no_valid_citations`).
9. **Sources and images.** `assemble_sources` describes every supplied passage, and
   `select_images` picks as primary image the figure closest to the most relevant cited
   text, with the other figures as related images.
10. The route serializes the `Answer` as `AnswerBody`, adding the URL of each figure crop.

## Deleting a document

`DELETE /api/v1/documents/{id}` reaches `DeleteDocument`
(`ingestion/use_cases/library.py`), which removes things from the most visible to the
least, so an interrupted deletion can simply be repeated:

1. Fails with 404 if the document does not exist, and with 409 while its latest job is
   pending or processing.
2. Deletes its points from Qdrant, so it stops appearing in answers immediately.
3. Deletes the figure crops, the page images and the PDF from blob storage.
4. Deletes the document row under a row lock, checking again that no job started.
   Foreign keys cascade to its jobs, elements and relationships.

## Related diagrams

The [backend page](../images/backend.svg) of the architecture drawing shows the same
flows as numbered badges on the arrows, ingestion in blue and questions in green, with
a Steps box that lists what each number means. Deletion appears in the box only.
