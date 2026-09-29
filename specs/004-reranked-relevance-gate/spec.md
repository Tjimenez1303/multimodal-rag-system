# Feature Specification: Reranked Relevance Gate

**Feature Branch**: `feature/reranked-relevance-gate`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "Reranked relevance gate for question answering. Today the
service decides whether to ask the answer model by checking that the best retrieved
passage reaches a fixed similarity of meaning, with an exception for identifiers such as
part numbers. This wrongly rejects short or keyword-style questions whose answer is in the
documents: 'Total Neto' against a budget whose second page shows only its net total is answered
with 'not enough information' even though that passage ranks first by a wide margin. It
also lets through questions the documents cannot answer, which then spend 6 to 13 seconds
of the answer model. The feature replaces the similarity check with a judgement from a
local ranking model that reads the question and each retrieved passage together, asks the
answer model only when a passage is judged to answer the question, and supplies the
passages to the answer model in judged order. The identifier exception stays, the
threshold is configurable and validated against the reference question set, and failures
of the ranking model follow the existing timeout and retry policy. Conversational
follow-up questions, splitting oversized tables and a larger ranking model are out of
scope."

## Clarifications

### Session 2026-09-29

- Q: When the ranking model stays unavailable, should the question fail or continue without the ranking? → A: It fails with a specific error that names the ranking model, within the question's total deadline, as search and answer model failures do. Continuing with the previous similarity check would silently bring back the rejections this feature removes.
- Q: Judging 16 candidates of the sample manuals took 1.4 s at the median and about 2 s at the 95th percentile, above the 1.5 s first set from shorter passages, while judging 8 met it but lost an answer held in a table. Which matters more? → A: Keep 16 candidates and allow judging up to 2.5 s, since it stays small next to the 6 to 13 s of an answer and keeps every answer reachable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get an answer to a short or keyword-style question (Priority: P1)

A technician types a few words instead of a full sentence, such as "Total Neto", "PSRAM" or
"corresponsal bancario", about something a document states plainly. The system recognizes
that a retrieved passage answers the question and returns a cited answer, as it does for
the same question written as a full sentence.

**Why this priority**: technicians search the way they search the web, with the label
printed on the page. Rejecting those questions while the passage that answers them ranks
first is the defect that motivates this feature, and it makes the product look broken in
the most common kind of question.

**Independent Test**: ingest a document that shows a labeled value (for example a budget
that shows "Total Neto: $880,900.0" on page 2), ask for the label alone and as a short
question, and confirm both receive an answer with that value that cites that document
and page.

**Acceptance Scenarios**:

1. **Given** a completed document whose page 2 shows "Total Neto: $880,900.0", **When**
   the technician asks "Total Neto" or "Cual es mi total Neto", **Then** the response is an
   answer that states that value and cites that document and page 2.
2. **Given** an answerable question of one to three words, **When** the passage that
   answers it is among the retrieved passages, **Then** the answer model is asked to
   answer, whatever the similarity of meaning between the question and that passage.
3. **Given** a question written in one language about a document written in another,
   **When** a retrieved passage answers it, **Then** the passage is recognized as
   answering it and the answer model is asked.
4. **Given** a question that holds an identifier, such as a part number, found as a whole
   word in a retrieved passage, **When** the question is answered, **Then** that passage
   is among those supplied and the answer model is asked, even when the ranking judges it
   below other passages or judges no passage relevant enough.

---

### User Story 2 - Stop questions the documents cannot answer before the answer model (Priority: P1)

A technician asks something close to the documents' topic that they do not state, such as
the number of employees of a company whose profile page describes its services, or the
price of a chip in a datasheet that lists no prices. The system recognizes that no
retrieved passage answers the question and replies at once that the documents do not
contain enough information, without spending the answer model's time.

**Why this priority**: a question on a related topic is the case where the current check
fails in the opposite direction. The technician waits 6 to 13 seconds for a
not-enough-information outcome that could be returned immediately, and every such
question takes the answer model away from answerable ones.

**Independent Test**: ask questions on the topic of a sample document whose answer is not
written in it, and confirm each receives a not-enough-information outcome without the
answer model being asked.

**Acceptance Scenarios**:

1. **Given** retrieved passages that share the question's topic but do not contain its
   answer, **When** no passage reaches the minimum judged relevance and none holds an
   identifier of the question, **Then** the response states that the documents do not
   contain enough information and the answer model is not asked.
2. **Given** a question unrelated to every document, **When** it is answered, **Then** the
   response is a not-enough-information outcome and the answer model is not asked.
3. **Given** a question the ranking lets through although the passages do not answer it,
   **When** the answer model receives it, **Then** the answer model's own abstention still
   produces a not-enough-information outcome, as the question answering feature defines.

---

### User Story 3 - Give the answer model the best passages first (Priority: P2)

The answer model receives the retrieved passages ordered by how well each one answers the
question, and each source in the response shows that judged relevance, so the passage
that answers the question is the first one the model reads and a reviewer can see why a
passage was used.

**Why this priority**: better ordering improves answers and citations, but the system
already answers correctly in most cases once the question reaches the answer model
(Story 1).

**Independent Test**: ask a question whose answer is in a known passage that search ranks
below other passages, and confirm that passage is supplied first and its source carries
the highest judged relevance.

**Acceptance Scenarios**:

1. **Given** retrieved passages, **When** they are supplied to the answer model, **Then**
   they are ordered from the highest judged relevance to the lowest, with the search rank
   deciding ties.
2. **Given** more candidate passages than the number supplied to the answer model, **When**
   the question is answered, **Then** the passages supplied are those with the highest
   judged relevance among the candidates.
3. **Given** an answered question, **When** the response is returned, **Then** every
   listed source carries its judged relevance, from 0 to 1, in addition to the details it
   already carries.

---

### User Story 4 - Get a clear outcome when the ranking model is slow or down (Priority: P2)

If the ranking model is slow or unavailable, the technician gets a predictable outcome
within the question's total deadline instead of a request that hangs, and uploads and job
status checks keep working.

**Why this priority**: the ranking model is one more local component that can be loading,
overloaded or stopped, and handling that predictably is an explicit evaluation criterion.

**Independent Test**: stop the ranking model, ask a question, and confirm the outcome
defined below arrives within the configured total deadline while uploads and status
checks still respond normally.

**Acceptance Scenarios**:

1. **Given** the ranking model is unavailable or times out beyond its retry budget,
   **When** a question is asked, **Then** the request fails with an error that states the
   ranking model is unavailable or timed out, within the configured total deadline, and no
   answer is written without the ranking.
2. **Given** a temporary ranking failure that clears before the retry budget runs out,
   **When** a question is asked, **Then** the technician receives a normal answer.
3. **Given** the ranking model is unavailable, **When** a document is uploaded or a job
   status is checked, **Then** those requests behave as usual.

---

### Edge Cases

- A retrieved passage is longer than the ranking model can read at once, such as a table
  that spans several pages. The passage is shortened to fit, keeping its section headings
  and its beginning, and the question never fails because of a passage's length.
- Several retrieved passages have the same text, for example the same manual uploaded
  twice. Repeated texts are dropped before judging, as they are today, so they neither
  take the answer model's places nor cost ranking time.
- Every candidate passage is judged below the minimum, but one of them holds an identifier
  of the question as a whole word. That passage is supplied and the answer model is
  asked, because exact identifiers are what keyword search finds reliably.
- A passage contains text phrased as an instruction to the ranking model, such as "answer
  yes". At most it raises its own judged relevance and lets the question reach the answer
  model, which still answers only from the supplied content and whose citations are still
  validated, as the question answering feature requires.
- A passage comes from a generated figure description or from low-confidence recognized
  text. It is judged like any other passage and keeps its origin flags in the response.
- The question is restricted to specific documents. Only candidates from those documents
  are judged.
- A question is cancelled while its passages are being judged. The system stops the
  judging and frees the question's place, as it does during search and generation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST judge, for each candidate passage retrieved for a question,
  how likely the passage is to contain the information that answers the question, as a
  score from 0 to 1 that is comparable across questions.
- **FR-002**: The judgement MUST assess whether the passage answers the question, not only
  whether it shares the question's topic, so that a passage about the right subject that
  lacks the requested fact scores low.
- **FR-003**: The judgement MUST read the question and the passage together and MUST work
  for questions and passages in English and Spanish, including a question in one of those
  languages about a passage in the other.
- **FR-004**: The number of candidate passages judged per question MUST be configurable,
  with a default of 16, and the number supplied to the answer model MUST stay the one the
  question answering feature defines (8 by default).
- **FR-005**: The answer model MUST be asked only when at least one of the passages
  supplied to it reaches a configurable minimum judged relevance (0.30 by default) or
  holds, as a whole word, an identifier of the question as the question answering feature
  defines it. Otherwise the response MUST be a not-enough-information outcome and the
  answer model MUST NOT be asked.
- **FR-006**: The similarity of meaning between the question and a passage MUST NOT decide
  on its own whether the answer model is asked. It remains available as an informational
  detail of each source.
- **FR-007**: The passages supplied to the answer model MUST be the candidates with the
  highest judged relevance, in descending order of judged relevance, with the search rank
  deciding ties. A candidate that holds, as a whole word, an identifier of the question
  MUST be supplied even when its judged relevance would leave it out, taking the place of
  the lowest judged passage, so that exact identifiers found by keyword search always
  reach the answer model.
- **FR-008**: Every source listed in a response MUST carry its judged relevance in
  addition to the details the question answering feature defines.
- **FR-009**: A passage longer than the ranking model's input limit MUST be shortened to
  fit, keeping its section headings and its beginning. A passage's length MUST NOT make a
  question fail.
- **FR-010**: The ranking model MUST run locally and be provisioned by the one-step
  startup together with the other models. Questions and document content MUST NOT be sent
  to external services.
- **FR-011**: Every call to the ranking model MUST have a configurable timeout, and
  temporary failures MUST be retried within a configurable budget. Time spent judging
  counts toward the question's total deadline.
- **FR-012**: When the ranking model stays unavailable, times out or returns an unusable
  response beyond the retry budget, the question MUST fail with a specific error that
  names the ranking model and the kind of failure, without exposing internal details. The
  system MUST NOT fall back to the similarity of meaning or to the search order.
- **FR-013**: Failures of the ranking model MUST NOT affect uploads, job status checks or
  document ingestion.
- **FR-014**: Every question MUST be recorded in the operational logs with the time spent
  judging and the highest judged relevance, in addition to what the question answering
  feature records, without recording the question text, the answer text or document
  content.
- **FR-015**: A cancelled question MUST stop any judging in progress and free its place,
  as the question answering feature requires for search and generation.

### Key Entities

This feature changes how the question answering feature
(`specs/002-grounded-question-answering/spec.md`) selects and orders the Retrieved Sources
of an answer, and reads the Retrieval Unit entity of the ingestion feature without
modifying it.

- **Relevance Judgement**: the score from 0 to 1 that the ranking model gives one
  candidate passage for one question. It exists only for the duration of the request.
- **Retrieved Source**: gains its judged relevance. Its other details are unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

The reference question set of the question answering feature is extended with at least 10
answerable questions of one to three words, at least 10 questions on the topic of a sample
document whose answer it does not contain, at least 3 answerable questions in Spanish
about an English document and 3 in English about a Spanish document, and the
labeled-value case of Story 1. Its identifier questions are kept.

- **SC-001**: At least 90% of the answerable questions in the reference set reach the
  answer model instead of being rejected before it.
- **SC-002**: At least 75% of the answerable questions of one to three words reach the
  answer model. On the labeled set of the Assumptions, the ranking let 7 of 9 such
  questions through and the similarity check it replaces let 2 of 9 through.
- **SC-003**: At least 70% of the unanswerable questions in the reference set receive a
  not-enough-information outcome without the answer model being asked, and at least 90%
  receive that outcome overall.
- **SC-004**: Judging adds less than 2.5 seconds to 95% of questions on the reference
  local environment, and the question answering feature's target of a complete answer in
  under 30 seconds for 95% of questions still holds.
- **SC-005**: When the ranking model is unavailable, 100% of questions end with the
  outcome defined in Story 4 within the configured total deadline, and uploads and status
  checks still complete in under 2 seconds.
- **SC-006**: The questions "Total Neto" and "Cual es mi total Neto" over the budget
  document of Story 1 are answered with its value and cite page 2.
- **SC-007**: The identifier criterion of the question answering feature still holds: for
  at least 95% of the identifier questions in the reference set, the retrieval unit that
  contains the identifier is among the units supplied to the answer model.

## Assumptions

- The ranking model is a small local model that runs next to the embedding and answer
  models provisioned by the one-step startup, and needs about 1.2 GB of additional memory.
- The minimum judged relevance of 0.30 comes from a labeled set of 31 questions over the
  documents indexed on 2026-09-29, measured with 8 judged candidates per question. Judging
  16 candidates can only raise a question's best judgement, so the default of 16 is
  confirmed against the extended reference set before release. On that set the ranking
  accepted 15 of 18 answerable questions, 0 of 9 questions on the documents' topic that
  they do not answer and 0 of 4 unrelated questions, while the similarity check accepted
  8, 5 and 0. The defaults are confirmed or tuned against the extended reference set and
  stay configurable.
- The answer model's own abstention remains the second protection against questions the
  documents do not answer, so a question the ranking lets through by mistake still ends as
  a not-enough-information outcome.
- Some short questions stay beyond the ranking model's reach, such as a question that
  names a concept with a word the document does not use (asking for a contact email
  when the passage shows only the address itself). They are rejected as today, and a larger
  ranking model is a later option.
- Conversational follow-up questions belong to a later feature. Splitting tables that are
  too long to judge in full belongs to the ingestion feature.
- The client shows the answer and its sources as the chat feature defines. Displaying the
  judged relevance in the client is not required by this feature.
