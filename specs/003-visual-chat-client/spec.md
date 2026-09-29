# Feature Specification: Visual Chat Client

**Feature Branch**: `feature/visual-chat-client`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "Visual chat client for the multimodal RAG system. A user
opens a web chat in the browser, types questions about the ingested technical manuals and
reads the answers in a conversation view that keeps the history of the session. Answers
render Markdown correctly (headings, lists, tables, code and emphasis). When an answer
depends on a diagram, table or image, the client shows the image closest to the relevant
text right next to the answer, with its caption and page, and the user can open it at full
size. Every answer shows where its information came from as document name and page (for
example "Source: Motor_Manual.pdf, page 12"), and sources that came from low-confidence
text recognition are visibly marked. When the system has no information to answer, the
client presents that clearly as a distinct state, not as a normal answer. While an answer
is being prepared the user sees that the system is working, and when the service fails or
times out the user sees an understandable message and can retry the question without
losing the conversation. The user can also upload a PDF from the client and follow its
processing (pending, processing with progress, completed or failed with its reason) until
it is ready to be asked about, and can optionally restrict questions to selected
documents. The client consumes the programmatic interfaces of the ingestion feature
(specs/001-async-pdf-ingestion) and the question answering feature
(specs/002-grounded-question-answering) and adds no answering logic of its own. It is
started together with the rest of the system by the one-step startup."

## Clarifications

### Session 2026-09-29

- Q: Where does the conversation history live? → A: In the browser, for the current session only. It is never stored on the server.
- Q: Can a question refer to an earlier turn of the conversation? → A: No. Each question is sent to the service on its own, so follow-up questions that depend on earlier turns are out of scope.
- Q: How many conversations and users does the client support? → A: One conversation at a time, with no user accounts or authentication, because the system serves a single organization as in the ingestion and question answering features.
- Q: Which languages and devices does the interface support? → A: The interface is in English and works on desktop browsers. A mobile layout is out of scope.
- Q: Is the answer shown progressively while it is written? → A: No. The answer is shown once it is complete, and streaming is out of scope.
- Q: How does the client behave while an answer is being written? → A: As agreed in the question answering feature, the client sends one question at a time. The send button becomes a stop button that cancels the question, and a question submitted meanwhile is held by the client and sent once the current answer arrives or is cancelled.
- Q: What happens to the conversation when the user reloads the page or closes the browser tab? → A: It survives a reload of the same tab and is lost when the tab is closed or the user starts a new conversation. It is never shared between tabs.
- Q: Can the user open the original PDF page behind a cited source? → A: Yes, as an image of the page. From every source line and every displayed figure the user opens the rendered page at full size, and the service gains a way to return the image of a document page.
- Q: Where does the primary image appear relative to the answer text? → A: To the right of the answer text, in a column of its own within the turn, with its caption and "document, page n" below it. The source lines sit under the answer text.
- Q: Where do uploading, the document list and document selection live relative to the conversation? → A: In a collapsible panel on the left of the chat view, open by default. When collapsed, it leaves an indicator of how many documents are still processing.
- Q: Does an error message show a reference that locates the request in the service's logs? → A: Yes, discreetly. Below the plain-English message the client shows a copyable "Reference: <id>" equal to the request's correlation identifier.
- Q: Can the technician read a whole document, not only the pages behind a source? → A: Yes. A ready document opens from the document panel in the page view, which then steps through every page of the document.
- Q: Can a document be deleted, and what does deleting remove? → A: Yes, from the document panel after a confirmation. Deleting removes the document, everything captured from it, its page images and the original file, so it can no longer be found or asked about. A document that is pending or processing cannot be deleted until its processing ends.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask a question and read the cited answer with its image (Priority: P1)

A technician opens the chat in the browser and asks a question about the manuals already
in the system, for example how to check the ignition leads on an engine. The answer
appears in the conversation, formatted as the service wrote it (headings, lists, tables,
code and emphasis). Below the answer, the technician sees where each piece of information
came from, for example "Source: Motor_Manual.pdf, page 12", and each numbered marker in
the text leads to its source. When the answer depends on a diagram, photo or table
figure, the closest image is shown right next to the answer with its caption, document
and page, and the technician can open it at full size. Earlier questions and answers stay
visible above, so the technician can scroll back through the session.

**Why this priority**: seeing a grounded answer together with its page reference and its
diagram is the core experience of the product and the key user-experience criterion of
the challenge. Without it, the other stories have nothing to support.

**Independent Test**: with a sample manual already ingested, ask a question whose answer
is explained by a known figure on a known page, and confirm the answer renders its
formatting, lists the expected document and page as its source, and shows the expected
figure next to it with caption and page, openable at full size. Ask a second question and
confirm the first turn is still visible.

**Acceptance Scenarios**:

1. **Given** at least one completed document, **When** the technician types a question
   and sends it, **Then** the question appears in the conversation and, once the answer is
   complete, the answer appears below it.
2. **Given** an answer that contains headings, ordered and unordered lists, a table,
   inline code, a code block, bold and italic text, **When** it is displayed, **Then**
   every element is rendered with its formatting and none of the formatting characters
   are shown as plain text.
3. **Given** an answered question, **When** the answer is displayed, **Then** every
   citation of the response appears as a source line with the document name and its
   pages, for example "Source: Motor_Manual.pdf, page 12" or "Source:
   Motor_Manual.pdf, pages 12–13", numbered like the markers in the answer text.
4. **Given** an answer whose text carries numbered markers such as `[1]`, **When** the
   technician activates a marker, **Then** the matching source line is brought into view
   and highlighted.
5. **Given** a response with a primary image, **When** the answer is displayed, **Then**
   the image is shown to the right of the answer text, in a column of its own within the
   turn, with its caption (or a note that it has no caption) and its document name and
   page below it, while the source lines sit under the answer text.
6. **Given** a displayed image, **When** the technician opens it, **Then** it is shown at
   full size with its caption, document name and page, and the technician can close that
   view and return to the same place in the conversation.
7. **Given** a response that also lists related images, **When** the answer is displayed,
   **Then** the related images are available as a secondary group under the primary
   image, each with its caption, document and page, without competing with it.
8. **Given** a source that the response flags as low-confidence recognized text, **When**
   it is displayed, **Then** it carries a visible mark and an explanation that the text was
   recognized from a scan with low confidence and should be checked against the page,
   with a direct way to open that page.
9. **Given** a source that the response marks as a generated figure description, **When**
   it is displayed, **Then** it carries a visible mark saying the content was described
   automatically, and lists any identifiers flagged as unverified.
10. **Given** an answer that the response marks as only partly covered, **When** it is
    displayed, **Then** the part the documents do not cover is shown as a clearly labeled
    note next to the answer.
11. **Given** a conversation with several turns, **When** a new answer arrives, **Then**
    it is brought into view and every earlier question and answer remains available in
    order.
12. **Given** a response that lists retrieved passages the answer did not cite, **When**
    the answer is displayed, **Then** those passages are available on demand, separate
    from the cited sources.
13. **Given** a source line or a displayed figure, **When** the technician opens its
    page, **Then** the rendered page of the original PDF is shown at full size with the
    document name and page number, and for a source that spans several pages the
    technician can move between those pages.

---

### User Story 2 - Understand when the system cannot answer, is working or has failed (Priority: P1)

A technician asks a question and immediately sees that the system is working on it. When
the manuals do not contain the answer, the reply looks clearly different from a normal
answer, so the technician does not mistake it for one. When the service is busy, fails or
takes too long, the technician reads a plain explanation and can send the same question
again with one action. The conversation is never lost along the way, and the technician
can stop a question that is taking too long.

**Why this priority**: a technician who cannot tell "the manual does not say this" from a
real answer, or who loses the conversation after an error, cannot trust the tool. Clear
states for waiting, no information and failure are part of asking a question, so they
share the top priority.

**Independent Test**: ask a question about a topic absent from every sample manual and
confirm the reply is shown in the distinct no-information state with no source and no
image. Stop the answer model, ask a question, confirm the waiting indicator appears, then
an understandable error with a retry action. Restart the answer model, retry, and confirm
the answer replaces the error while every earlier turn is intact.

**Acceptance Scenarios**:

1. **Given** a question has been sent, **When** its answer has not arrived yet, **Then**
   the conversation shows that the system is working on it, and the send button becomes a
   stop button.
2. **Given** a response with the not-enough-information status, **When** it is displayed,
   **Then** it appears in a visually distinct state, labeled as no information found, with
   no source lines and no image.
3. **Given** a not-enough-information response because no document is ready yet, **When**
   it is displayed, **Then** it tells the technician that no documents are ready and how
   to upload one.
4. **Given** a not-enough-information response to a question restricted to selected
   documents, **When** it is displayed, **Then** it says the selected documents do not
   contain the information and offers to ask the same question across all documents.
5. **Given** the service reports that the answer model or search is unavailable or timed
   out, **When** the error is displayed, **Then** the technician reads a plain message
   naming what went wrong (for example "The answer model is not responding") and a retry
   action, with no technical codes or internal details in the message itself, and below
   it a copyable reference that identifies the request in the service's logs.
6. **Given** the service reports that it is busy, **When** the error is displayed,
   **Then** the message says the system is busy and when the question can be retried.
7. **Given** the service cannot be reached at all, or no response arrives within the
   client's wait limit, **When** the error is displayed, **Then** the message says the
   service could not be reached or did not answer in time, with a retry action.
8. **Given** a failed question, **When** the technician retries it, **Then** the same
   question is sent again with the same document restriction, the result takes the place
   of the error in the same turn, and every other turn is unchanged.
9. **Given** a question that is being answered, **When** the technician presses the stop
   button, **Then** the question is cancelled, its turn is marked as stopped with a retry
   action, and the input is ready for a new question.
10. **Given** a question that is being answered, **When** the technician submits another
    question, **Then** the new question appears as waiting to be sent and is sent once the
    current answer arrives or is cancelled.
11. **Given** a question the service rejects as invalid (for example too long), **When**
    the rejection is displayed, **Then** the reason is shown and the question text stays
    available to be edited and sent again.
12. **Given** a conversation with several turns, **When** the technician reloads the page
    in the same browser tab, **Then** the conversation is still there.

---

### User Story 3 - Upload a manual and follow its processing (Priority: P2)

A technician adds a new manual from the chat itself. The upload is acknowledged right
away, and the technician watches the document move through pending, processing (with the
current stage and pages processed out of the total) and completed, or failed with a
readable reason. Once completed, the document is marked as ready and can be asked about
immediately, without leaving the conversation.

**Why this priority**: adding manuals is how the library grows, and following the
processing tells the technician when a manual can be asked about. Questions still work
without it on documents that were already ingested.

**Independent Test**: upload a sample manual from the client, confirm it appears as
pending and then processing with a changing page count, wait until it shows as ready, and
ask a question answered by it. Upload a file that is not a PDF and a corrupt PDF, and
confirm each shows a readable reason.

**Acceptance Scenarios**:

1. **Given** the chat is open, **When** the technician chooses a PDF to upload from the
   document panel, **Then** the transfer progress is shown while the file is sent, and
   the document then appears in the document list as pending, without leaving or
   clearing the conversation.
2. **Given** a document whose processing has started, **When** its status changes on the
   service, **Then** the client shows it as processing with the current stage in plain
   words and the number of pages processed out of the total.
3. **Given** a document whose processing completed, **When** the status is shown, **Then**
   the document is marked as ready, with a short summary of what was captured (pages,
   tables and images), and it can be asked about.
4. **Given** a document whose processing failed, **When** the status is shown, **Then**
   the document is marked as failed with the readable reason given by the service, and the
   technician can upload the file again to retry.
5. **Given** a file the service rejects (not a PDF, too large, too many pages or
   unreadable), **When** the upload ends, **Then** the reason is shown next to that file
   and no document is added to the list.
6. **Given** a file whose content was already ingested, **When** it is uploaded, **Then**
   the client says it was already ingested and shows the existing document as ready.
7. **Given** a job that is being processed again after an interruption, **When** its
   status is shown, **Then** the client indicates that processing is being retried.
8. **Given** documents that are still processing, **When** the technician reloads the page,
   **Then** the document list shows their current status and keeps following them until
   they end.
9. **Given** several files uploaded one after another, **When** they are processed,
   **Then** each one shows its own status independently.
10. **Given** documents that are still pending or processing, **When** the technician
    collapses the document panel, **Then** the conversation takes the freed width and a
    visible indicator shows how many documents are still being processed.

---

### User Story 4 - Restrict questions to selected documents (Priority: P3)

A technician working on one machine selects that machine's manuals, so the next questions
are answered only from them. The selection stays visible near the question input, each
answer shows which documents it was restricted to, and the technician can clear the
selection to ask across all documents again.

**Why this priority**: useful when the library holds manuals for similar machines, but the
chat works without it.

**Independent Test**: with two ingested manuals that cover a similar topic, select one of
them, ask a question, and confirm the question shows the restriction and every displayed
source and image comes from the selected manual. Clear the selection and confirm the next
question is asked across all documents.

**Acceptance Scenarios**:

1. **Given** several ready documents, **When** the technician selects one or more of them,
   **Then** the selection is shown near the question input and every question sent
   afterwards is restricted to those documents.
2. **Given** documents that are pending, processing or failed, **When** the technician
   looks for documents to select, **Then** those documents cannot be selected and their
   status explains why.
3. **Given** an active selection, **When** a question is sent, **Then** its turn in the
   conversation shows the names of the documents it was restricted to.
4. **Given** an active selection, **When** the technician clears it, **Then** the next
   question is asked across all ready documents.
5. **Given** a selection that includes a document the service no longer accepts (unknown
   or not ready), **When** a question is sent, **Then** the service's message naming that
   document is shown and the technician can adjust the selection and retry.
6. **Given** a library with many documents, **When** the technician looks for one to
   select, **Then** the technician can find it by typing part of its name.

---

### User Story 5 - Read a whole manual and remove one that is no longer needed (Priority: P2)

A technician opens a ready manual from the document panel and pages through it, to check
what it contains before asking about it. When a manual is obsolete or was uploaded by
mistake, the technician deletes it from the panel, after confirming, and it is no longer
listed, searched or cited.

**Why this priority**: reading a manual and keeping the library clean are part of
managing documents, next to uploading them. Questions work without either.

**Independent Test**: open a ready document from the panel and step to its last page.
Delete it, confirm it leaves the list, and ask a question it used to answer to confirm
it is no longer cited. Try to delete a document while it is processing and confirm the
client does not offer it.

**Acceptance Scenarios**:

1. **Given** a ready document, **When** the technician chooses to view it, **Then** its
   first page opens in the page view, labeled with the document name and page, and the
   technician can step through every page of the document.
2. **Given** a ready or failed document, **When** the technician chooses to delete it,
   **Then** the client asks for confirmation, naming the document, before deleting it.
3. **Given** a confirmed deletion, **When** it succeeds, **Then** the document leaves the
   document list, and later questions never cite it.
4. **Given** a document that is pending or processing, **When** the technician looks at
   it, **Then** no delete action is offered until its processing ends.
5. **Given** a deletion the service refuses or cannot complete, **When** it ends, **Then**
   the client shows the reason with its reference and the document stays listed.
6. **Given** earlier turns that cite a deleted document, **When** the technician opens one
   of its pages, or reloads the conversation, **Then** the page view and the figures say
   they are unavailable, and the answer text and its source lines stay as they were. A
   figure already on screen may stay visible until the reload.

---

### Edge Cases

- The service is unreachable when the client opens. The client shows a clear connection
  notice instead of an empty or broken view, and recovers without a manual reload once the
  service is available.
- The stored image of a figure cannot be loaded. The image area shows that the image is
  unavailable, and the document name, page and caption remain visible.
- The image of a document page cannot be produced or loaded. The page view says the page
  is unavailable, keeps the document name and page number visible, and the rest of the
  answer is unaffected.
- A figure has no caption. The image is shown with its document and page and a note that
  it has no caption.
- An answer contains a table wider than the conversation area. The table stays readable
  and can be scrolled sideways within the answer, without breaking the page layout.
- An answer or a retrieved passage contains raw markup or script-like text that came from
  a document. It is displayed as text and never executed or rendered as active content.
- A citation spans several pages, or several citations point to the same page. Each
  source line lists its pages once, in order.
- A very tall or very wide figure. The image is scaled to fit next to the answer and keeps
  its proportions, and the full-size view shows it completely.
- The answer is written in a language other than English. The answer is shown as
  returned, while the interface labels stay in English.
- The technician sends several questions while an answer is being written. They are held
  in the order submitted and sent one at a time.
- The technician stops a question and immediately sends a new one. The stopped turn keeps
  its stopped state, and the new question is answered normally.
- The conversation grows long. Scrolling and typing stay responsive, and every turn stays
  available until the tab is closed or the technician starts a new conversation.
- A document the technician had selected fails when reprocessed, or disappears from the
  library. It is removed from the active selection and the technician is told why.
- The service returns a response that the client cannot interpret. The turn shows an
  understandable error with a retry action instead of a blank or partial answer.
- The same file is uploaded twice at the same time. Both uploads end showing the same
  document, not two copies.
- A document is deleted from another tab or tool while it is listed. The next refresh of
  the list drops it, and a deletion attempted from this tab simply removes it from the
  list.
- A document starts processing again, because its file was uploaded anew, between the
  confirmation and the deletion. The service refuses the deletion and the client shows
  why.

## Requirements *(mandatory)*

### Functional Requirements

#### Conversation

- **FR-001**: The client MUST let users type a natural-language question and send it with
  a button or with the keyboard, and MUST let them write a question on several lines. An
  empty question MUST NOT be sendable.
- **FR-002**: The client MUST show the conversation as an ordered list of turns, each with
  the question and its outcome, and MUST keep every turn available until the browser tab
  is closed or the user starts a new conversation.
- **FR-003**: The conversation MUST be kept only in the browser and MUST survive a page
  reload in the same tab. It MUST be discarded when the tab is closed, MUST NOT be shared
  with other tabs and MUST NOT be sent to or stored by the service.
- **FR-004**: Users MUST be able to start a new conversation, which clears the current
  one after they confirm.
- **FR-005**: Each question MUST be sent to the service on its own, without earlier turns.
- **FR-006**: The client MUST send one question at a time. While a question is being
  answered, the send button MUST become a stop button, and questions submitted meanwhile
  MUST be held in order and sent one at a time once the current answer arrives or is
  cancelled.
- **FR-007**: Stopping a question MUST cancel it on the service and mark its turn as
  stopped, with a retry action.

#### Answer display

- **FR-008**: The client MUST render the answer's Markdown, covering at least headings,
  ordered and unordered lists including nested ones, tables, inline code, code blocks,
  bold and italic text.
- **FR-009**: The client MUST NOT execute or render as active content any markup, script
  or embedded resource contained in an answer, a source excerpt or a caption. Such content
  MUST be shown as text.
- **FR-010**: For every citation of an answered response, the client MUST show a source
  line with the document name and pages in the form "Source: <document name>, page <n>"
  or "Source: <document name>, pages <n>–<m>" (non-contiguous pages listed individually),
  numbered like the citation.
- **FR-011**: Numbered markers in the answer text MUST be displayed as references that,
  when activated, bring the matching source line into view and highlight it.
- **FR-012**: Each source line MUST let the user see its section, an excerpt of the
  passage and, when the source is a table, its rows and columns rendered as a table.
- **FR-013**: A source flagged as low-confidence recognized text MUST carry a visible mark
  with a short explanation that the text should be checked against its page. A source
  marked as a generated figure description MUST carry a distinct visible mark and list
  its unverified identifiers, if any.
- **FR-014**: Retrieved passages that the answer does not cite MUST be available on
  demand and visually separated from the cited sources.
- **FR-015**: When a response has a primary image, the client MUST show it to the right
  of the answer text, in a column of its own within the turn, with its caption (or a note
  that it has none), document name and page below it, as returned by the service. The
  source lines MUST sit under the answer text. When a response has no primary image, the
  answer text MUST use the full width of the turn.
- **FR-016**: Users MUST be able to open any displayed image at full size, with its
  caption, document name and page, and to close that view with the mouse or the keyboard,
  returning to the same place in the conversation.
- **FR-017**: Related images of a response MUST be available as a secondary group in the
  image column, under the primary image, each with its caption, document name and page.
- **FR-018**: From every source line and every displayed figure, users MUST be able to
  open the rendered page of the original PDF at full size, labeled with the document name
  and page number. For a source that spans several pages, users MUST be able to move
  between those pages. The page view MUST close like the full-size image view.
- **FR-019**: The service MUST return the image of any page of a completed document on
  request, and MUST answer with a specific error when the document is unknown, not
  completed or has no such page. This is the only change this feature makes to the
  service, and it adds no answering logic.
- **FR-020**: When the response states which part of the question the documents do not
  cover, the client MUST show that part as a labeled note attached to the answer.
- **FR-021**: A response with the not-enough-information status MUST be shown in a state
  that is visually distinct from an answer, labeled as no information found, with no
  source lines and no images. The client MUST add guidance that matches the reason given
  by the service: upload a document when none is ready, ask across all documents when the
  question was restricted, or rephrase the question otherwise.
- **FR-022**: The client MUST NOT add, remove, reorder or rewrite answer text, citations,
  sources or images. It MUST display the service's outcome as returned and MUST NOT
  contain any retrieval, answering or image-selection logic of its own.

#### Waiting and errors

- **FR-023**: From the moment a question is sent until its outcome arrives, its turn MUST
  show that the system is working on it.
- **FR-024**: The client MUST translate every failure reported by the service into a
  plain-English message that names what went wrong without technical codes or internal
  details, covering at least: the answer model unavailable, timed out or unable to
  produce an answer, search unavailable or timed out, the question exceeding the time
  limit, the system being busy, an invalid question and a document restriction that
  names unknown or unready documents.
- **FR-025**: Every failed question or upload MUST show, below the plain-English
  message, a discreet and copyable reference ("Reference: <id>") equal to the correlation
  identifier the service records for that request. The client MUST attach that identifier
  to every request it sends, so a reference exists even when the service could not be
  reached.
- **FR-026**: When the service is busy, the message MUST say when the question can be
  retried, using the wait indicated by the service.
- **FR-027**: When the service cannot be reached, or no response arrives within a
  configurable client wait limit longer than the service's total deadline, the client
  MUST show that the service could not be reached or did not answer in time.
- **FR-028**: Stopped turns, and failed turns whose failure can succeed when sent
  again, MUST offer a retry action that sends the same question with the same document
  restriction. Failures that would repeat unchanged, such as an invalid question or a
  restriction naming unknown or unready documents, MUST instead return the question to
  the input for editing. The result MUST take the place of the
  failure in the same turn and MUST leave every other turn unchanged.
- **FR-029**: When the service rejects a question as invalid, the client MUST show the
  reason and keep the question text available for editing.
- **FR-030**: When the service cannot be reached, the client MUST show a visible
  connection notice, in addition to the per-turn message of FR-027, and MUST clear it
  without a manual reload once the service responds again.

#### Documents

- **FR-031**: Uploading, the document list and document selection MUST live in a
  collapsible panel on the left of the chat view, open by default. When collapsed, the
  panel MUST leave a visible indicator of how many documents are still pending or
  processing, and the conversation MUST use the freed width.
- **FR-032**: Users MUST be able to upload a PDF from the document panel without leaving
  or clearing the conversation. The client MUST show the transfer progress while the file is
  sent and MAY refuse a file that is not a PDF before sending it. Every other limit is
  checked by the service.
- **FR-033**: The client MUST show a document list with every document known to the
  service and its latest processing status, newest first, loading further documents on
  demand when the library is large.
- **FR-034**: For each document, the client MUST show its status as pending, processing,
  ready (completed) or failed. Processing MUST show the current stage in plain words and
  the pages processed out of the total, a retried job MUST be indicated as retrying, a
  completed document MUST show a short summary of what was captured, and a failed
  document MUST show the readable reason given by the service.
- **FR-035**: The client MUST keep following every document that is pending or
  processing, including after a page reload, until it is completed or failed, and MUST
  stop following it afterwards.
- **FR-036**: When an upload is rejected, the client MUST show the service's reason next
  to that file and MUST NOT add it to the document list. When the content was already
  ingested, the client MUST say so and show the existing document.
- **FR-037**: A failed document MUST offer a way to upload the file again.

#### Document restriction

- **FR-038**: Users MUST be able to select one or more ready documents to restrict their
  questions, up to the maximum the service accepts, and to find a document by typing part
  of its name. Documents that are not ready MUST NOT be selectable.
- **FR-039**: The active selection MUST be visible near the question input, and clearing
  it MUST make the next question apply to all ready documents.
- **FR-040**: Every turn asked with a restriction MUST show the names of the documents it
  was restricted to.
- **FR-041**: When a selected document stops being ready or disappears from the library,
  the client MUST remove it from the selection and tell the user why.

#### Interface and delivery

- **FR-042**: All interface text MUST be in English. Answers MUST be shown in the language
  the service wrote them in.
- **FR-043**: The interface MUST work in current desktop versions of the major browsers
  on windows of 1280 by 720 pixels or larger.
- **FR-044**: Every action in the client MUST be operable with the keyboard, and every
  displayed image MUST have a text alternative based on its caption, document and page.
- **FR-045**: The client MUST be started by the system's one-step startup together with
  the rest of the system, MUST report its own health to that startup, and MUST be
  reachable at a documented local address once the startup finishes.
- **FR-046**: The client MUST communicate only with the system's own service and MUST
  NOT load resources from, or send questions, documents or usage data to, any external
  service.

#### Document viewing and deletion

- **FR-047**: Users MUST be able to open any ready document from the document panel in
  the page view of FR-018, starting at its first page and stepping through every page of
  the document.
- **FR-048**: Users MUST be able to delete a ready or failed document from the document
  panel after confirming, in a confirmation that names the document. Deleting MUST remove
  the document, everything captured from it, its page images and its original file, so
  it is no longer listed, searched or cited.
- **FR-049**: A pending or processing document MUST NOT offer deletion, and the service
  MUST refuse to delete it. A failed deletion MUST show the reason with its reference
  and leave the document listed.

### Key Entities

This feature displays the Document and Job entities of the ingestion feature
(`specs/001-async-pdf-ingestion/spec.md`) and the Answer, Citation, Retrieved Source and
Answer Image entities of the question answering feature
(`specs/002-grounded-question-answering/spec.md`). The only change it makes to them is
deleting a document, with its jobs and captured content, when the user asks for it
(FR-048).

- **Conversation**: the ordered list of turns of the current browser tab. It lives only in
  the browser, survives a reload of that tab and is cleared when the tab is closed or a
  new conversation starts.
- **Turn**: one question with the documents it was restricted to, if any, and its state:
  held, waiting for the answer, answered, no information found, stopped or failed. An
  answered or no-information turn holds the service's response as returned. A failed
  turn holds the plain-English failure message, its reference and whether it can be
  retried.
- **Document Selection**: the set of ready documents that restricts the next questions.
  It is empty when questions apply to all documents.
- **Tracked Upload**: a file the user is sending or has sent from this client, with its
  transfer progress, the service's rejection reason when it was refused, or the document
  it became.

## Success Criteria *(mandatory)*

### Measurable Outcomes

The reference answer set referred to below holds at least 20 responses captured from the
question answering feature over the sample manuals, or written to its contract when a
response cannot be produced on demand, including answers with each Markdown
element listed in FR-008, answers with and without a primary image, multi-page citations,
low-confidence and generated sources, partial answers, every not-enough-information reason
and every failure the service can report.

- **SC-001**: In 100% of answered responses in the reference set, every citation is shown
  as a source line with the correct document name and pages, and the primary image, when
  present, is shown next to the answer with its caption and page.
- **SC-002**: 100% of the Markdown elements in the reference set render with their
  formatting, and no formatting characters remain visible as plain text.
- **SC-003**: 100% of sources flagged as low-confidence recognized text or as generated
  descriptions in the reference set carry their visible mark.
- **SC-004**: In a walkthrough with at least 5 people who have not used the client
  before, every participant tells a no-information reply apart from an answer, and at
  least 90% find the document and page of an answer's source and open its image at full
  size within 10 seconds of the answer appearing.
- **SC-005**: A first-time user uploads a manual, waits until it is ready and asks a
  question about it without written instructions in at least 90% of attempts during the
  walkthrough.
- **SC-006**: The working indicator appears within 0.5 seconds of sending a question in
  100% of attempts.
- **SC-007**: 100% of failures in the reference set are shown with a plain-English message
  and, where the failure is retryable, a retry action. After a retry, the conversation
  keeps 100% of its earlier turns in the same order.
- **SC-008**: 100% of turns are still present after a page reload in the same tab.
- **SC-009**: A change of processing status on the service is reflected in the client
  within 5 seconds in at least 95% of observations.
- **SC-010**: A conversation of 50 turns, each with a primary image, stays responsive:
  a typed character appears in the input within 100 milliseconds, and an image opens at
  full size within 300 milliseconds.
- **SC-011**: For 100% of source lines and figures in the reference set, opening the page
  shows the page of the original PDF whose number is displayed, within 3 seconds on the
  reference local environment.
- **SC-012**: After the one-step startup completes on the reference local environment,
  the client is reachable at its documented address with no additional step.
- **SC-013**: After a document is deleted, 100% of the questions it used to answer, asked
  again, return no source from it, and it no longer appears in the document list.

## Assumptions

- The system serves a single organization in a local or demo deployment. Authentication,
  user accounts and per-user document permissions are out of scope, as in the ingestion
  and question answering features.
- The client relies on the programmatic interfaces of the ingestion feature (upload,
  document list, job status and stored images) and of the question answering feature
  (questions, cancellation and their error reports) as specified in those features. The
  only additions this feature makes to them are the page image of FR-019, rendered while
  the ingestion feature extracts the PDF, and the document deletion of FR-048.
- Exporting, sharing or reopening past conversations is out of scope.
- Answers arrive complete, as specified by the question answering feature, so progressive
  display of an answer while it is written is out of scope.
- Follow-up questions that depend on earlier turns, rating or giving feedback on answers,
  copying or exporting answers and usage analytics are out of scope.
- The mobile layout is out of scope. Desktop windows of 1280 by 720 pixels or larger are
  the supported target.
- The document list reflects what the service reports. Documents uploaded from other
  clients or tools appear in it as well.
- The client's wait limit defaults to the question answering feature's total deadline
  plus a margin, and is set during planning.
- Accessibility follows common practice for web applications (keyboard operation, text
  alternatives and readable contrast). A formal accessibility audit is out of scope.
- The sample manuals and the reference local environment are those defined by the
  ingestion and question answering features.
