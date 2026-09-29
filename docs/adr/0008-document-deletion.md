# 0008. Deleting a document

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Manuals go out of date, and some are uploaded by mistake. A technician needs to remove
one from the library so that it is no longer listed, searched or cited, and so that its
file and everything captured from it stop taking space. A document is spread over the
search index, the file storage and the database, and it may be in the middle of being
processed when someone asks to delete it.

How is a document deleted, and what happens when deletion is interrupted or collides
with processing?

## Decision drivers

- Once a deletion succeeds, no answer cites the document again.
- An interrupted deletion never leaves the document half removed with no way to finish.
- Processing is never disturbed by a deletion.
- Deleting is a deliberate act, confirmed by the user.

## Considered options

1. Delete right away in the API, from the most visible piece to the least, and refuse
   while the document is being processed.
2. Queue a deletion job for the worker, as uploads are processed.
3. Allow deletion during processing by cancelling the running job first.

## Decision outcome

Chosen option: **delete right away in the API, from the most visible piece to the
least, and refuse while the document is being processed**. The document panel offers
"Delete" on ready and failed documents, behind a confirmation that names the file. The
service removes the document's search entries first, then its page images, figures and
original file, and finally its records. A document whose processing is pending or
running is refused with a message that says why.

### Consequences

- Good, because the document stops being cited as soon as its search entries are gone,
  the first step.
- Good, because every step tolerates what is already gone, so a deletion interrupted by
  an unavailable index or disk is finished by asking again. The document stays listed
  until then.
- Good, because a deletion takes well under a second, with no job to follow.
- Bad, because a technician has to wait for processing to end before deleting a manual
  uploaded by mistake.
- Bad, because earlier answers in an open conversation keep citing the deleted document,
  and their pages and figures show as unavailable.

## Annex: technical evidence

### Route behavior

`DELETE /api/v1/documents/{document_id}`

| Case | Answer |
|---|---|
| Ready or failed document | 204, no body |
| Unknown document | 404 `document_not_found`, which the client treats as already deleted |
| Latest job pending or processing | 409 `ingestion_in_progress` |
| Search index or storage unavailable | 503, with the document still listed |

### Order of removal

1. `VectorIndex.delete_document`, which also treats a missing Qdrant collection as
   nothing to delete.
2. `BlobStorage.delete_tree` over `figures/{document_id}` and `pages/{document_id}`,
   then the original PDF.
3. `DocumentRepository.delete`, whose foreign keys cascade to jobs, elements and
   relationships.

Deleting the records first was rejected. An index failure after it would leave
searchable entries for a document that no longer exists, with no route to retry.

### Concurrency

The repository locks the document row with `SELECT … FOR UPDATE` before it checks for
a pending or processing job, in the same transaction as the `DELETE`. A new upload of the
same file either commits its job first and is seen by the check, or waits on the lock
and then finds no document. A plain `DELETE … WHERE NOT EXISTS` was rejected: under READ
COMMITTED its subquery does not see a job committed while it waits, and the cascade
would remove that job silently.

### Verification

On the Compose stack, a one-page sample was refused with 409 while processing. Once
ready, it was deleted from the panel, after which the blob volume held no file, the
Qdrant collection no point and PostgreSQL no document, job or element row.

### Sources

- https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE
- https://www.postgresql.org/docs/18/transaction-iso.html#XACT-READ-COMMITTED
- https://qdrant.tech/documentation/concepts/points/#delete-points
- Full analysis: `specs/003-visual-chat-client/research.md`, section 18
