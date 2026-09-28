# Feature Specification: Asynchronous PDF Ingestion

**Feature Branch**: `feature/async-pdf-ingestion`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "Asynchronous ingestion of technical PDFs with job tracking.
Uploading a PDF returns a job identifier right away, processing happens in the background,
and the job moves through pending, processing, completed and failed with queryable progress.
Processing extracts structured text, tables and images with their page and position on the
page, relates text to nearby images, groups content by document structure instead of fixed
lengths, and indexes it so it can be searched later."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload a manual and follow its processing (Priority: P1)

A technician uploads a technical manual in PDF format. The system accepts it immediately
and gives back a tracking identifier, without making the technician wait for the document
to be processed. The technician uses that identifier to check whether processing is
pending, in progress, finished or failed, how far along it is, and why it failed if it did.

**Why this priority**: nothing else in the product works until documents can enter the
system, and heavy documents must not freeze or time out the service while they are
processed.

**Independent Test**: upload a sample manual, confirm a tracking identifier comes back
immediately, then poll its status until it reaches completed. Upload a corrupt file and
confirm it is rejected or ends as failed with a readable reason.

**Acceptance Scenarios**:

1. **Given** a valid PDF within the size limit, **When** the technician uploads it,
   **Then** the system acknowledges the upload with a unique tracking identifier before
   any content processing starts, and the job status is pending.
2. **Given** a job that is being processed, **When** the technician checks its status,
   **Then** the status is processing and shows the current stage and the number of pages
   processed out of the total.
3. **Given** a job that finished successfully, **When** the technician checks its status,
   **Then** the status is completed and includes a summary of what was captured (pages,
   text sections, tables, images and retrieval units).
4. **Given** a job whose processing could not finish, **When** the technician checks its
   status, **Then** the status is failed and includes a human-readable reason.
5. **Given** a file that is not a PDF or exceeds the size limit, **When** the technician
   uploads it, **Then** the upload is rejected immediately with a message that explains
   why, and no job is created.
6. **Given** an unknown tracking identifier, **When** the technician checks its status,
   **Then** the system answers that the job does not exist.

---

### User Story 2 - Faithful capture of text, tables and images (Priority: P2)

When a manual is processed, the system keeps its structure: running text, tables and
images (diagrams, schematics, photos) are captured as distinct elements. Every element
remembers the page it came from and where it sits on that page, and the system records
which text belongs with which image. Content is grouped into retrieval units that follow
the document's own structure (sections, headings, tables, figure captions) rather than
being cut at arbitrary lengths.

**Why this priority**: answers can only cite the right page and show the right diagram if
this information is captured at ingestion time. It is the core of the multimodal
challenge, but it depends on Story 1 to receive documents.

**Independent Test**: ingest a sample manual with known figures and tables, then inspect
the captured elements of the completed document. Check that each element has its page
and position, that tables stay whole, that figures are linked to their captions or
surrounding text, and that no retrieval unit cuts a sentence or a table in half.

**Acceptance Scenarios**:

1. **Given** a completed document, **When** its captured elements are inspected, **Then**
   every element states its type (text, table or image), its page number and its position
   on the page using one documented coordinate convention.
2. **Given** a page with a diagram and its caption, **When** the document is processed,
   **Then** the diagram is linked to its caption and to the nearest related text on the
   same page.
3. **Given** a table that spans part of a page, **When** the document is processed,
   **Then** the table is captured as a table, with rows and columns preserved, and is not
   merged into surrounding prose.
4. **Given** a long section with headings, **When** the document is processed, **Then**
   retrieval units start and end on structural boundaries (heading, paragraph, table,
   figure) and each one keeps a reference to its section, pages and related images.
5. **Given** a completed document, **When** any of its images is requested, **Then** the
   original image is available for display.

---

### User Story 3 - Ingest many manuals without degrading the service (Priority: P2)

An administrator loads a large collection of manuals at once, for example a hundred of
them. The system queues them all, processes them in the background at the pace its
capacity allows, and keeps accepting uploads and answering status checks promptly the
whole time. Adding processing capacity makes the batch finish sooner without any change
to how uploads or status checks work.

**Why this priority**: scaling from one manual to a hundred is an explicit evaluation
criterion, and a slow or unresponsive service during bulk loads would undermine trust in
the whole product.

**Independent Test**: submit a batch of one hundred sample documents in quick succession
and measure upload and status response times during processing. Then repeat with more
processing capacity and confirm total processing time drops.

**Acceptance Scenarios**:

1. **Given** one hundred documents queued for processing, **When** a new document is
   uploaded, **Then** it is acknowledged as quickly as when the queue is empty.
2. **Given** one hundred documents queued for processing, **When** any job status is
   checked, **Then** the answer arrives promptly and reflects the job's real state.
3. **Given** processing stops unexpectedly in the middle of a job, **When**
   processing resumes, **Then** the job is picked up again or marked failed with a reason,
   and the document never ends up with duplicated or partial content in the index.

---

### User Story 4 - Browse the document library (Priority: P3)

A technician opens the list of documents the system knows about and sees, for each one,
its name, page count, ingestion status and when it was added, so they know which manuals
can already be asked about.

**Why this priority**: useful for users and for the future chat client, but questions can
be asked without it once documents are ingested.

**Independent Test**: ingest two documents, let one fail on purpose, then list the library
and confirm both appear with the correct status and details.

**Acceptance Scenarios**:

1. **Given** documents in different states, **When** the library is listed, **Then** each
   document appears once with its name, page count (when known), latest status and date
   added.
2. **Given** a document in the library, **When** its details are opened, **Then** the
   technician can reach its latest job status and its captured elements.

---

### Edge Cases

- A file with a `.pdf` name that is not actually a PDF is rejected at upload, based on its
  content rather than its name.
- A password-protected or encrypted PDF ends as failed with a reason that says so.
- A PDF that opens but is damaged partway through ends as failed, and no partial content
  from it stays searchable.
- Pages without a text layer (scanned pages) are kept as page images and flagged. A
  document with no extractable text on any page ends as failed with a reason that says so.
- Uploading a document whose content is identical to one already completed returns the
  existing document and job instead of processing it again.
- Uploading a document whose content is identical to one that previously failed starts a
  new processing job for it.
- A temporary outage of an external service used during processing is retried
  automatically. If it persists beyond the retry budget, the job ends as failed with a
  reason naming the unavailable service, and the document can be submitted again.
- An image that appears on several pages (such as a logo) is not treated as relevant
  context for every page.
- A figure whose caption sits on the following page is still linked to that caption when
  the relationship can be detected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept PDF uploads and return a unique job identifier and a
  document identifier without waiting for content processing to happen.
- **FR-002**: The system MUST reject, at upload time and without creating a job, files
  that are not PDFs by content or that exceed the configured size or page limits, with a
  message stating the reason.
- **FR-003**: The system MUST process uploaded documents in the background, separately
  from the handling of user requests.
- **FR-004**: Each job MUST be in exactly one of the states pending, processing, completed
  or failed, and MUST only move forward (pending to processing, processing to completed or
  failed).
- **FR-005**: The system MUST let users query a job by its identifier and return its state,
  current stage, pages processed out of the total, timestamps and, when failed, a
  human-readable failure reason.
- **FR-006**: Job state and progress MUST be stored durably so they survive restarts of
  any part of the system.
- **FR-007**: The system MUST extract running text, tables and images from each document
  as distinct typed elements.
- **FR-008**: Every extracted element MUST record its document, page number and position
  on the page, expressed in a single documented coordinate convention (unit and origin)
  shared across the system.
- **FR-009**: The system MUST record relationships between images and text (captions and
  nearby text on the same page, or an adjacent page when the caption continues there) and
  between tables and their titles.
- **FR-010**: The system MUST group content into retrieval units that follow the
  document's structure (sections, headings, paragraphs, tables, figure captions). It MUST
  NOT split content purely by a fixed number of characters or words. A size ceiling MAY
  apply only within a structural unit.
- **FR-011**: Each retrieval unit MUST keep references to its document, section, page
  numbers and related images.
- **FR-012**: The system MUST index retrieval units so they can be searched both by meaning
  and by exact keywords in later features.
- **FR-013**: The system MUST store every extracted image so it can be displayed later,
  linked to its document, page and position.
- **FR-014**: The system MUST flag images that repeat across many pages (such as logos or
  page decorations) so they are not offered as relevant context.
- **FR-015**: Processing the same document again (after a retry, a restart or a crash)
  MUST NOT create duplicate elements or retrieval units.
- **FR-016**: The system MUST recognize an upload whose content is identical to an already
  completed document and return that document and its job instead of processing it again.
- **FR-017**: Temporary failures of external services used during processing MUST be
  retried automatically within a configurable budget. When the budget is exhausted the job
  MUST end as failed with a reason naming the failing service.
- **FR-018**: When a job fails, no content from that attempt MUST remain searchable.
- **FR-019**: The system MUST let users list known documents with their name, page count,
  latest job status and date added, and open a document's captured elements.
- **FR-020**: Processing capacity MUST be increasable without changes to how uploads or
  status queries behave.
- **FR-021**: Every upload, state transition and failure MUST be recorded in the
  operational logs with the job identifier, without recording document content or
  personal data.

### Key Entities

- **Document**: an uploaded PDF. It has a name, a content fingerprint used to detect
  identical uploads, a page count, the date it was added and a link to its jobs.
- **Ingestion Job**: one processing attempt for a document. It has a state, a current
  stage, progress (pages processed out of total), start and end times, a failure reason
  when failed, and a result summary when completed.
- **Extracted Element**: a piece of content taken from one page. It has a type (text, table
  or image), the page number, the position on the page and its content (text, table
  structure or a stored image).
- **Element Relationship**: a link between an image or table and the text that describes
  it (caption, title or nearby paragraph), with the kind of relationship.
- **Retrieval Unit**: a structurally coherent group of content prepared for search. It
  references its document, section, pages, source elements and related images.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users receive a tracking identifier in under 2 seconds for any accepted
  upload up to the size limit, whatever the size of the document.
- **SC-002**: Job status reflects a change in state or progress within 5 seconds of it
  happening.
- **SC-003**: A 100-page technical manual with figures and tables reaches completed in
  under 10 minutes on the reference local environment.
- **SC-004**: 100% of captured elements carry a document, page number and position.
- **SC-005**: In the sample document set, at least 90% of figures that have a caption are
  linked to that caption, and no table or sentence is split across two retrieval units.
- **SC-006**: While 100 documents are queued, 95% of uploads and status checks still
  complete in under 2 seconds and none of them time out.
- **SC-007**: 100% of failed jobs carry a human-readable reason.
- **SC-008**: Re-processing a document after a retry, restart or crash produces zero
  duplicate elements or retrieval units.

## Assumptions

- The system serves a single organization in a local or demo deployment. Authentication
  and per-user document permissions are out of scope for this feature.
- Uploads are limited to 100 MB and 500 pages per file by default, and both limits are
  configurable.
- Scanned pages are not converted to text in this feature. They are stored as page images
  so they can still be shown to users.
- Documents are primarily in English or Spanish, and language detection is not required.
- Job and document records are kept until they are deleted manually. Document deletion is
  out of scope for this feature.
- Uploads happen through the service's programmatic interface. Uploading from the chat
  client belongs to the client feature.
- Answering questions, hybrid search ranking and the chat client are separate features
  that consume what this feature produces.
- The reference local environment is the full system started locally with the project's
  one-step startup on a typical developer laptop.
