# Feature Specification: Grounded Question Answering

**Feature Branch**: `feature/grounded-question-answering`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "Grounded question answering over ingested technical PDFs. A
user asks a question in natural language through the service's programmatic interface and
receives an answer built only from the content of the documents already ingested. Retrieval
combines meaning-based search and exact keyword search over the retrieval units. Every
answer cites its sources as document name and page, lists the retrieval units it used and,
when the answer depends on a diagram, table or image, returns the image closest to the
relevant text with its page and caption. When the retrieved content is not enough, the
system says so instead of guessing and never cites a page that was not retrieved.
Low-confidence recognized text is flagged, questions can be restricted to specific
documents, and slow or unavailable components fail with a specific error after bounded
retries."

## Clarifications

### Session 2026-09-29

- Q: How many retrieval units feed an answer, and when is the retrieved content "not enough"? → A: Both are configurable with sensible defaults. A question uses the 8 most relevant retrieval units by default, and when none of them reaches the configured minimum relevance the system answers that the documents do not contain enough information.
- Q: How many images does an answer return? → A: At most one primary image, the one closest to the text the answer relies on, plus a list of other related images.
- Q: In which language is the answer written? → A: In the language of the question, whatever the language of the documents.
- Q: Who may ask questions? → A: Anyone who can reach the service. There is no authentication, as in the ingestion feature, because the system serves a single organization.
- Q: How is a table the answer relies on presented? → A: Its source carries the table's rows and columns so a client can render it as a table. No picture of the table is produced, and a primary image is returned only when a figure is linked to that table.
- Q: How is each citation tied to the part of the answer it supports? → A: The answer text carries numbered markers (for example `[1]`) placed after the statements they support, and each marker points to one entry of the structured citation list with its document name and pages.
- Q: Which retrieval units does the response list as sources? → A: Every unit supplied to the answer model for the question (8 by default), each marked as cited or not cited by the answer.
- Q: What happens when more questions arrive at once than the local answer model can handle? → A: A configurable number of questions is answered at the same time (2 by default) and a bounded line holds the rest (6 by default). When the line is full, new questions are rejected at once with a "busy, retry later" error. A client can cancel a waiting or running question, which frees its place. The chat client sends one question at a time and shows a stop button while an answer is being written. A question submitted meanwhile is held by the client and sent once the current answer arrives or is cancelled.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask a question and get a cited answer (Priority: P1)

A technician asks a question about the manuals already in the system, for example how to
check the ignition leads on an engine. The system finds the relevant passages, writes an
answer using only those passages, and returns it together with the sources it relied on:
the document name and page of each one (for example "Source: Motor_Manual.pdf, page 12")
and the retrieval units that were used.

**Why this priority**: answering questions from the manuals is the purpose of the product,
and a technical answer is only trusted when the technician can see exactly where it came
from.

**Independent Test**: ingest a sample manual, ask a question whose answer is on a known
page, and confirm the answer is correct, cites that document and page, and lists the
retrieval units used.

**Acceptance Scenarios**:

1. **Given** at least one completed document that contains the answer, **When** the
   technician asks a question, **Then** the response contains an answer, the document name
   and page of every source it relied on, and every retrieval unit supplied to the answer
   model, each marked as cited or not cited.
2. **Given** an answer built from several passages, **When** the response is returned,
   **Then** each supported statement ends with a numbered marker (for example `[1]`), and
   every marker points to an entry of the structured citation list with its document name
   and pages.
3. **Given** a retrieval unit that spans several pages (for example a table that continues
   on the next page), **When** it supports the answer, **Then** its citation lists every
   page it spans.
4. **Given** a question written in Spanish about a manual written in English, **When** the
   technician asks it, **Then** the answer is written in Spanish and the cited document
   names, pages and exact identifiers stay as they appear in the manual.
5. **Given** a supporting passage that came from text recognition with low confidence,
   **When** the response is returned, **Then** that source is flagged as low-confidence
   recognized text.
6. **Given** a supporting passage that came from a generated figure description, **When**
   the response is returned, **Then** that source is marked as a generated description and
   carries any identifiers that were flagged as unverified at ingestion.

---

### User Story 2 - Say so when the documents do not contain the answer (Priority: P1)

A technician asks something the manuals do not cover, or asks for a value that is not
written anywhere. Instead of inventing an answer, the system states clearly that the
ingested documents do not contain enough information, and it does not cite any page.

**Why this priority**: a wrong answer about a technical procedure can damage equipment or
hurt someone. Admitting a gap is an explicit requirement of the challenge and the main
protection against invented answers.

**Independent Test**: ask a question about a topic absent from every sample manual and
confirm the response states that the information is not available, has no citations and
returns no image.

**Acceptance Scenarios**:

1. **Given** no retrieved content reaches the minimum relevance, **When** the question is
   answered, **Then** the response states that the documents do not contain enough
   information, has no citations and no images, and the answer model is not asked to
   write an answer.
2. **Given** retrieved content that is related to the topic but does not answer the
   question, **When** the question is answered, **Then** the response says the information
   is not available instead of guessing.
3. **Given** retrieved content that answers only part of the question, **When** the
   question is answered, **Then** the response answers the supported part and states which
   part the documents do not cover.
4. **Given** an answer model that cites a document or page that was not among the
   retrieved content, **When** the response is assembled, **Then** that citation is
   removed, and if no valid citation remains the response states that there is not enough
   information.
5. **Given** a retrieved passage that contains text phrased as an instruction (for example
   "ignore the previous rules"), **When** the question is answered, **Then** that text is
   treated only as document content and does not change how the system answers.
6. **Given** no document has completed ingestion, **When** a question is asked, **Then**
   the response states that there are no searchable documents yet.

---

### User Story 3 - Find exact identifiers such as part numbers and error codes (Priority: P2)

A technician asks about a specific part number, error code, valve label or exact term
that appears in a manual, possibly only inside a diagram. The system finds the passage or
figure that contains that exact identifier, even when the rest of the question is phrased
loosely, and answers from it.

**Why this priority**: technicians often search by the code printed on a part or shown on
a display. Search by meaning alone tends to miss exact codes, so combining it with exact
keyword search is what makes these questions work.

**Independent Test**: pick identifiers that appear only once in the sample manuals,
including labels that appear only inside a diagram, ask about each one and confirm the
retrieval unit holding it is among those used and the answer cites its page.

**Acceptance Scenarios**:

1. **Given** a part number that appears in a single retrieval unit, **When** the
   technician asks about that part number, **Then** that retrieval unit is among the ones
   used and its page is cited.
2. **Given** a label that appears only inside a diagram, **When** the technician asks about
   it, **Then** the figure's retrieval unit is among the ones used.
3. **Given** a question that paraphrases the manual without sharing its words, **When**
   the technician asks it, **Then** the relevant passage is still found by meaning.

---

### User Story 4 - See the diagram the answer depends on (Priority: P2)

When the answer relies on a diagram, schematic, photo or table, the response includes the
image closest to the text the answer relies on, with its document, page and caption, so a
client can show it next to the answer. Other images related to the cited content are
listed as well, in case the technician wants to see them.

**Why this priority**: showing the right diagram next to the answer is the key
multimodal requirement of the challenge, but it builds on a cited answer (Story 1).

**Independent Test**: ask a question whose answer is explained by a known figure in a
sample manual and confirm that figure is the primary image, with its page and caption, and
that the image itself can be retrieved for display.

**Acceptance Scenarios**:

1. **Given** an answer that relies on a passage linked to a figure, **When** the response
   is returned, **Then** it includes that figure as the primary image, with its document,
   page, caption and a reference that lets a client display the image.
2. **Given** a cited passage with several nearby figures, **When** the primary image is
   chosen, **Then** it is the figure closest to that passage on the page, and the other
   figures appear in the list of related images.
3. **Given** an answer that relies on a table, **When** the response is returned, **Then**
   the table's source carries its rows and columns so a client can render it as a table,
   and a primary image is returned only when a figure is linked to that table.
4. **Given** an answer that relies only on running text with no related figure, **When**
   the response is returned, **Then** it has no primary image.
5. **Given** a figure flagged at ingestion as decorative or repeated across pages (such as
   a logo), **When** images are selected, **Then** it is never returned as a primary or
   related image.
6. **Given** a response that states there is not enough information, **When** it is
   returned, **Then** it has no primary image and no related images.

---

### User Story 5 - Get a clear error when a component is slow or down (Priority: P2)

If the answer model or a search component is slow or unavailable, the technician gets a
specific, understandable error within a bounded time instead of a request that hangs. The
rest of the system, such as uploads and job status checks, keeps working.

**Why this priority**: network drops, overloaded local models and slow responses are
expected conditions, and handling them predictably is an explicit evaluation criterion.

**Independent Test**: stop the answer model, ask a question, and confirm the request fails
within the configured deadline with an error naming the answer model, while uploads and
status checks still respond normally. Repeat with the search component stopped.

**Acceptance Scenarios**:

1. **Given** the answer model is unavailable, **When** a question is asked, **Then** the
   system retries within its configured budget and then fails with an error that states
   the answer model is unavailable, within the configured total deadline.
2. **Given** the search component is unavailable, **When** a question is asked, **Then**
   the request fails with an error that states search is unavailable, within the
   configured total deadline.
3. **Given** the answer model responds more slowly than its configured timeout, **When** a
   question is asked, **Then** the request fails with an error that states the answer model
   timed out, and no partial answer is returned as if it were complete.
4. **Given** the answer model or search is unavailable, **When** a document is uploaded or
   a job status is checked, **Then** those requests behave as usual.
5. **Given** a temporary failure that clears before the retry budget runs out, **When** a
   question is asked, **Then** the technician receives a normal answer.
6. **Given** a question that is empty or longer than the configured limit, **When** it is
   submitted, **Then** it is rejected immediately with a message that explains why, and no
   search or answer model call is made.
7. **Given** the configured number of questions is already being answered and the
   waiting line is full, **When** another question is submitted, **Then** it is rejected
   at once with an error stating that the system is busy and the question can be retried
   later.
8. **Given** a question that is waiting or being answered, **When** the client cancels
   the request, **Then** the system stops working on it and frees its place for the next
   question.

---

### User Story 6 - Restrict a question to specific documents (Priority: P3)

A technician working on one machine restricts the question to that machine's manuals, so
passages from other manuals cannot leak into the answer.

**Why this priority**: useful when the library holds manuals for similar machines, but
questions work without it.

**Independent Test**: ingest two manuals that both cover a similar topic, ask a question
restricted to one of them, and confirm every source and image comes from that manual.

**Acceptance Scenarios**:

1. **Given** a question restricted to specific documents, **When** it is answered, **Then**
   every source, citation and image comes from those documents only.
2. **Given** a restriction that names a document that does not exist, **When** the
   question is submitted, **Then** it is rejected with a message naming the unknown
   document.
3. **Given** a restriction that names a document whose ingestion has not completed,
   **When** the question is submitted, **Then** it is rejected with a message naming the
   document that is not ready yet.
4. **Given** a restricted question whose answer exists only in other documents, **When**
   it is answered, **Then** the response states that the selected documents do not contain
   enough information.

---

### Edge Cases

- A document that is still being processed, or whose ingestion failed, never contributes
  content to an answer, even partially.
- A question that mixes two unrelated topics is answered for the topics the documents
  cover, and the response states which parts are not covered.
- Two manuals give conflicting values for the same thing (for example two torque values
  for different models). The answer presents both values with their own citations instead
  of choosing one silently.
- A question that contains an identifier absent from every document is answered as not
  enough information, rather than with a passage about a similar identifier presented as
  if it matched.
- A question asks the system to use general knowledge or to ignore the documents. The
  answer is still built only from the retrieved content.
- A question written in a language other than English or Spanish is answered in that
  language when the answer model supports it, still grounded in the retrieved content.
- A retrieval unit whose document record is missing is reported as an internal error
  rather than cited without a name.
- Several retrieved units come from the same page. The page is cited once per supported
  statement, not repeated for every unit.
- The answer model returns a malformed response, or one without the expected fields,
  after its retries. The request fails with an error stating that the answer could not be
  generated. An answer the model deliberately leaves empty because the sources do not
  cover the question is a not-enough-information outcome, not an error.
- Questions arrive while a large batch of documents is being ingested. They are still
  answered, possibly more slowly, and none of them hang beyond the configured deadline.
- A figure's stored image is missing when the response is assembled. The problem is
  reported as an internal error instead of returning a reference that cannot be displayed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST let users submit a natural-language question through the
  service's programmatic interface and return the answer in the same response.
- **FR-002**: The system MUST reject, before any search, a question that is empty or longer
  than a configurable limit (2,000 characters by default), with a message stating why.
- **FR-003**: The system MUST search only retrieval units of documents whose ingestion
  completed, and MUST NOT use content from documents that are pending, processing or
  failed.
- **FR-004**: Search MUST combine search by meaning and exact keyword search over the
  retrieval units and merge both result lists into a single ranking, so that questions
  with exact identifiers and paraphrased questions both find their passages.
- **FR-005**: The number of retrieval units used per question MUST be configurable, with a
  default of 8.
- **FR-006**: When no retrieved unit reaches a configurable minimum relevance, the system
  MUST answer that the documents do not contain enough information, without asking the
  answer model to write an answer.
- **FR-007**: Answers MUST be written only from the retrieved content. The instructions
  given to the answer model MUST be kept separate from the retrieved content, and text
  inside retrieved content MUST be treated as data, never as instructions.
- **FR-008**: When the retrieved content does not answer the question, the response MUST
  say so explicitly instead of guessing. When it answers only part of the question, the
  response MUST answer that part and state which part is not covered.
- **FR-009**: Every response MUST have a status that distinguishes an answer from a
  not-enough-information outcome.
- **FR-010**: Every response that contains an answer MUST include a structured list of
  numbered citations, each with the document name and page numbers of a source it relied
  on. The answer text MUST place the matching numbered marker (for example `[1]`) after
  each statement that the citation supports, and every citation in the list MUST be
  referenced by at least one marker.
- **FR-011**: The system MUST verify that every cited document and page belongs to the
  retrieval units supplied for that question and MUST drop any citation that does not,
  together with its markers in the answer text. A marker that points to no citation MUST
  also be removed. When the answer model writes an answer without any citation marker,
  the system MUST attribute each statement to the supplied unit it matches best, and
  only when the match reaches a configurable minimum. When no valid citation remains, the
  response MUST be a not-enough-information outcome.
- **FR-012**: Every response MUST list the retrieval units used, meaning every unit
  supplied to the answer model for that question, each with its document, section,
  pages, content type (text, table or figure), an excerpt of its content and whether the
  answer cites it. The list is empty when the answer model was not asked to answer.
- **FR-013**: A source whose content came from text recognition with a confidence below
  a configurable threshold (0.90 by default) MUST be flagged as low-confidence recognized
  text.
- **FR-014**: A source whose content came from a generated figure description MUST be
  marked as generated, together with any identifiers flagged as unverified at ingestion.
- **FR-015**: When an answer relies on a retrieval unit that is a figure or is linked to
  figures, the response MUST include at most one primary image: the figure closest to the
  supporting text on the page, using the relationships recorded at ingestion. The primary
  image MUST carry its document, page, caption, position on the page and a reference that
  lets a client display it.
- **FR-016**: Other figures linked to the cited retrieval units MUST be returned as a list
  of related images with the same details as the primary image, ordered by relevance.
- **FR-017**: Figures flagged at ingestion as decorative or repeated across pages MUST
  NOT be returned as primary or related images.
- **FR-018**: When an answer relies on a table, its retrieved source MUST carry the
  table's rows and columns so a client can render it as a table. A table MUST NOT be
  returned as an image, and a primary image MUST be returned only when a figure is linked
  to that table.
- **FR-019**: The answer MUST be written in the language of the question. Document names,
  identifiers, codes and values quoted from the documents MUST keep their original form.
- **FR-020**: Users MUST be able to restrict a question to one or more documents. The
  system MUST reject a restriction that names unknown documents or documents whose
  ingestion has not completed, with a message naming them.
- **FR-021**: Each question MUST be answered independently of any earlier question.
- **FR-022**: Every call to the answer model and to the search components MUST have a
  configurable timeout, and temporary failures MUST be retried within a configurable
  budget. The whole question MUST finish, successfully or not, within a configurable
  total deadline.
- **FR-023**: When the answer model or a search component stays unavailable, times out or
  returns an unusable response beyond the retry budget, the request MUST fail with a
  specific error that names the component and the kind of failure, without exposing
  internal details.
- **FR-024**: Failures while answering questions MUST NOT affect uploads, job status
  checks or document ingestion.
- **FR-025**: Answers MUST be generated by the locally running answer model provisioned
  by the one-step startup. Questions and document content MUST NOT be sent to external
  services.
- **FR-026**: Every question MUST be recorded in the operational logs with a correlation
  identifier, its outcome status, the number of retrieval units used and the time spent
  on search and on generation, without recording the question text, the answer text or
  document content.
- **FR-027**: The answer text MAY use lightweight formatting (Markdown), such as lists and
  emphasis, so a client can render it.
- **FR-028**: The number of questions answered at the same time MUST be limited by a
  configurable value (2 by default). Further questions MUST wait in a line of
  configurable length (6 by default), and the waiting time counts toward the total
  deadline. When the line is full, a new question MUST be rejected at once with an error
  stating that the system is busy and the question can be retried later.
- **FR-029**: When the client cancels a question that is waiting or being answered, the
  system MUST stop working on it, including any generation in progress, and free its
  place for the next question.

### Key Entities

This feature reads the Document, Extracted Element, Element Relationship and Retrieval
Unit entities defined by the ingestion feature (`specs/001-async-pdf-ingestion/spec.md`)
and never modifies them.

- **Question**: a natural-language question with an optional list of documents that
  restricts where the answer may come from. It exists only for the duration of the
  request and is not stored.
- **Answer**: the response to a question. It has a status (answered or not enough
  information), the answer text in the language of the question, its citations, the
  retrieved sources used, an optional primary image and a list of related images.
- **Citation**: a numbered link between the statements of the answer that carry its
  marker and the document name and page numbers that support them. It always points to a
  retrieval unit supplied for that question.
- **Retrieved Source**: a retrieval unit supplied to the answer model for the question,
  with its document, section, pages, content type, excerpt, rows and columns when it is a
  table, relevance, whether the answer cites it, and its origin flags (low-confidence
  recognized text, generated description, unverified identifiers).
- **Answer Image**: a figure returned with an answer, either primary or related. It has
  its document, page, caption, position on the page and a reference to the stored image.

## Success Criteria *(mandatory)*

### Measurable Outcomes

The reference question set referred to below holds at least 40 questions over the sample
manuals, in English and Spanish, including paraphrased questions, questions about exact
identifiers, questions whose answer relies on a figure, questions asked in a language
different from the manual, and at least 10 questions the manuals do not answer. Each
question records its expected document, pages and, when relevant, expected figure.

- **SC-001**: For at least 90% of the answerable questions in the reference set, the
  answer is correct and its citations include the expected document and page.
- **SC-002**: 100% of citations in all responses point to a document and page that were
  among the retrieved content for that question.
- **SC-003**: At least 90% of the unanswerable questions in the reference set receive a
  not-enough-information outcome, and no more than 10% of the answerable questions do.
- **SC-004**: For at least 95% of the identifier questions in the reference set, the
  retrieval unit that contains the identifier is among the units used.
- **SC-005**: For at least 80% of the questions whose answer relies on a figure, the
  primary image is the expected figure, and for at least 95% of them the expected figure
  is either the primary image or among the related images.
- **SC-006**: 100% of answers in the reference set are written in the language of the
  question.
- **SC-007**: 95% of questions receive their complete answer in under 30 seconds on the
  reference local environment while no document is being ingested.
- **SC-008**: When the answer model or a search component is unavailable, 100% of
  questions end with a specific error within the configured total deadline, and uploads
  and status checks still complete in under 2 seconds.
- **SC-009**: While 100 documents are queued for ingestion, questions are still answered
  and none of them exceeds the configured total deadline.
- **SC-010**: 100% of sources that come from low-confidence recognized text are flagged
  as such in the response.
- **SC-011**: When more questions arrive than the system can answer or hold in line,
  100% of the extra questions receive the busy error in under 1 second, and every
  accepted question still ends within the configured total deadline.

## Assumptions

- The system serves a single organization in a local or demo deployment. Authentication
  and per-user document permissions are out of scope, as in the ingestion feature.
- The minimum relevance for a not-enough-information outcome and the default total
  deadline are tuned during planning against the reference question set, and both stay
  configurable.
- The answer model runs locally on the reference local environment defined by the
  ingestion feature and shares its graphics accelerator with figure description, so
  answers can be slower while documents are being described.
- Conversation history, follow-up questions that refer to earlier answers, answers
  delivered progressively as they are written, and the chat client belong to the chat
  feature. This feature answers each question on its own and returns the full answer at
  once.
- The chat client sends one question at a time per conversation, as common chat
  assistants do. While an answer is being written, its send button becomes a stop button
  that cancels the question. The user can still write and submit the next question, which
  the client holds and sends once the current answer arrives or is cancelled. That
  behavior belongs to the chat feature and relies on the cancellation this feature
  provides.
- Uploading documents and browsing the library are provided by the ingestion feature.
- Displaying an image relies on the image storage and retrieval provided by the ingestion
  feature.
- Questions and answers are not stored. Keeping a history of questions, collecting user
  feedback on answers and usage analytics are out of scope.
- Rewriting or expanding the question before search, and reordering results with a
  second ranking model, are not required by this feature and may be considered during
  planning only if the success criteria cannot be met without them.
- The sample manuals are the documents in the project's sample set, which include a
  digital English manual, a digital Spanish guide and a scanned English manual.
