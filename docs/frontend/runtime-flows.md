# Runtime flows

This page follows the three things a user does, component by component. Paths are
relative to `frontend/src/`. Every request goes to the same origin, and nginx proxies
`/api/v1/*` to the API.

## Uploading a PDF and following its processing

1. `UploadControl` (`documents/UploadControl.tsx`) opens a hidden file input that accepts
   several PDFs. Each picked file is tracked in local state as `sending`.
2. `isPdf` rejects files that are not PDFs before anything is sent.
3. `uploadDocument` (`api/upload.ts`) sends `POST /api/v1/documents` with
   `XMLHttpRequest` rather than `fetch`, because only XHR reports upload progress. A
   progress bar follows the sent fraction, and a transfer with no progress for 60 seconds
   is given up.
4. The response is validated with the generated `zUploadAccepted` schema. On success the
   row shows the file as received, or as already ingested when identical content was
   uploaded before, and `onAccepted` refreshes the library. An error body is parsed as
   an RFC 9457 problem and turned into a message by `toUploadFailure`.
5. `useLibrary` (`documents/useLibrary.ts`) lists documents with a TanStack
   `useInfiniteQuery` on `GET /api/v1/documents`. For every document whose latest job is
   missing, pending or processing, a `useQueries` entry polls
   `GET /api/v1/documents/{id}` every `statusPollSeconds`. Each answer is written back
   into the cached list, so once a job is final the document leaves the polled set and
   polling stops.
6. `DocumentStatus` shows the badge, the stage in plain words ("Reading pages",
   "Describing figures"…), page progress, retries, then either the summary of what was
   found or the failure reason.

## Asking a question

1. `QuestionInput` (`conversation/QuestionInput.tsx`), built on AI Elements'
   `PromptInput`, sends on Enter and ignores blank text.
2. `useQuestionQueue.submit` dispatches `submitted`. The reducer
   (`conversation/state.ts`) adds a turn as `waiting`, or as `held` when another question
   is still being answered. `useConversation` saves the conversation to
   `sessionStorage` after every change.
3. An effect in `useQuestionQueue` finds the waiting turn and calls `askQuestion`
   (`api/questions.ts`), which goes through `callService` to the generated SDK:
   `POST /api/v1/questions`, waiting at most `answerWaitSeconds`. While waiting, the turn
   shows a spinner and the send button becomes a stop button.
4. The outcome is dispatched:
   - `answered`, which becomes the `answered` or `no_information` state depending on the
     response's status;
   - `failed`, with a message and an action from `toTurnFailure`. A rejected question is
     put back into the input to be edited;
   - `stopped`, when the user pressed stop, which aborts the request.

   When nothing is waiting any more, the oldest held turn is sent next.
5. `TurnView` (`conversation/TurnView.tsx`) renders the turn by state. An answered turn
   is wrapped in `CitationProvider` and laid out in two columns:
   - `AnswerMarkdown` renders the answer with Streamdown. The `citationMarkers` plugin
     turns each `[n]` that matches a real citation into a `CitationMarker`, a small badge
     that shows the source on hover and, when clicked, highlights and scrolls to the
     matching line of `SourceList`.
   - `SourceList` shows one numbered line per citation, with badges for low-confidence
     OCR and generated figure descriptions, the passage or table rows, and an
     "Open page" button. Passages the model saw but did not cite stay in a collapsible
     below.
   - `ImageColumn` shows the primary figure, then the related ones. Each `FigureCard`
     loads the image URL returned by the API,
     `/api/v1/documents/{id}/images/{element_id}`, and offers the figure at full size or
     the page it comes from.
6. A `no_information` turn renders `NoInformationState`, with guidance that fits the
   reason and, when no document is ready, a button that opens the upload control.

## Viewing and deleting a document

- **View.** A ready row in `DocumentList` offers "View document", a `PageDialog` over
  every page of the document. Each page is the PNG stored at ingestion,
  `GET /api/v1/documents/{id}/pages/{n}/image`, with previous and next buttons. The same
  dialog opens the pages of a citation or a figure.
- **Delete.** Ready and failed rows offer `DeleteDocumentDialog`. On confirmation it
  sends `DELETE /api/v1/documents/{id}` through `callService`. On success the dialog
  closes and `useLibrary.remove` drops the document from the cached list at once, then
  reads the library again. A document already gone counts as deleted, and a document
  still being processed shows why it cannot be deleted yet. The dialog cannot be closed
  while the deletion runs.

## Related diagram

The [frontend page](../images/frontend.svg) of the architecture drawing shows these
flows as numbered badges on the arrows, upload in green, asking in purple, view and
delete in orange, with a Steps box that lists what each number means.
