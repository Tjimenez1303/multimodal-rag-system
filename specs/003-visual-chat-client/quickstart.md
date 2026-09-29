# Quickstart: Visual Chat Client

This guide proves the feature end to end on the running system. The client's routes,
configuration and failure messages are in [contracts/client.md](contracts/client.md), the
page image operation is in [contracts/openapi.yaml](contracts/openapi.yaml), and the
browser state is in [data-model.md](data-model.md).

## Prerequisites

- The system set up as in `specs/001-async-pdf-ingestion/quickstart.md`, with Docker Model
  Runner enabled and `.env` created from `.env.example`.
- Node 24 (the version in `frontend/.node-version`) for the frontend checks. The running
  system itself needs only Docker.
- A current desktop Chrome, Firefox or Safari, in a window of at least 1280 × 720.
- Documents ingested before this feature have no page images. Recreate the volumes once:

  ```bash
  docker compose down -v
  ```

## Start the system (FR-045, SC-012)

Check that the frontend port is free, then start everything:

```bash
lsof -iTCP:3000 -sTCP:LISTEN
docker compose up -d --build --wait
```

Expected:

- `docker compose ps` lists `frontend` as healthy next to `api`, `worker`, `postgres` and
  `qdrant`.
- <http://localhost:3000> shows the chat with the document panel open on the left.
- `curl -s localhost:3000/config.json` returns the three runtime values.

## Scenario 1: upload and follow processing (US3, FR-031 to FR-037, SC-009)

1. In the document panel, upload `docs/samples/faa-powerplant-ch4-ignition-electrical.pdf`.
   The transfer progress runs, then the document appears as Pending.
2. Watch it move to Processing with "Reading pages" and a growing "n of 71 pages", then
   through the later stages, to Ready with a summary of pages, tables and images.
3. While it processes, reload the page. The document is still followed.
4. Collapse the panel. The conversation widens, and a badge counts the documents still
   processing.
5. Upload the same file again. The client says it was already ingested.
6. Upload any non-PDF file. It is refused at once with "Only PDF files can be uploaded."
7. Upload the other two sample manuals and wait until all three are Ready.

For SC-009, note the time a stage changes in `docker compose logs -f worker` and when the
client shows it. It must be within 5 seconds.

## Scenario 2: cited answer with its image and page (US1, FR-008 to FR-020, SC-001, SC-011)

Ask "How is a shunt generator wired?".

Expected:

- **Working state.** It appears at once (SC-006), and the send button becomes a stop
  button.
- **Answer.** It renders its Markdown formatting and ends its statements with linked
  markers such as `[1]`.
- **Markers.** Activating `[1]` scrolls to "Source:
  faa-powerplant-ch4-ignition-electrical.pdf, page …" and highlights it.
- **Image column.** The primary figure sits to the right of the answer text, with its
  caption and "document, page n" below it, and the related figures under it.
- **Full-size view.** Opening the figure shows it at full size, and Escape returns to the
  same place in the conversation.
- **Page view.** "Open page" on a source line or on the figure shows the rendered PDF
  page within 3 seconds (SC-011). A multi-page source lets you step between its pages.
- **Other passages.** "Other retrieved passages" lists the uncited sources.

Also check the page route directly:

```bash
DOC=$(curl -s localhost:3000/api/v1/documents | jq -r '.items[] | select(.file_name | startswith("faa")) | .id')
curl -s -o /tmp/page.png -w '%{http_code} %{content_type}\n' "localhost:3000/api/v1/documents/$DOC/pages/12/image" && file /tmp/page.png
curl -s "localhost:3000/api/v1/documents/$DOC/pages/999/image" | jq '{status, code}'
```

Expected: `200 image/png` with a PNG of page 12, then 404 `page_not_found`.

## Scenario 3: low-confidence and generated sources (US1, FR-013, SC-003)

Ask a question answered by the scanned welding manual, for example "How do I start the
welding machine engine?".

Expected: sources from low-confidence recognized pages carry the low-confidence mark and
its explanation. Sources built from figure descriptions carry the "described
automatically" mark and list any unverified identifiers.

## Scenario 4: no information (US2, FR-021)

1. Ask "What is the recommended tire pressure for a bicycle?". The reply shows the
   distinct "No information found" state with no sources and no images, and suggests
   rephrasing.
2. Select only the INSST guide and ask "What is a shunt generator?". The reply says the
   selected documents do not contain it and offers "Ask across all documents", which
   answers it from the FAA manual.

## Scenario 5: stop, hold, retry and reload (US2, FR-006, FR-007, FR-028, SC-008)

1. Ask a question, and while it is answered submit two more. They appear as waiting to
   be sent and are answered one after another.
2. Ask a question and press stop after 2 seconds. The turn shows Stopped with a retry
   action. `docker compose logs api --since 10s | grep -i cancel` shows the question
   cancelled through nginx.
3. Retry it. The answer replaces the stopped state in the same turn.
4. Reload the page. Every turn is still there, in order (SC-008). Close the tab and open
   <http://localhost:3000> again. The conversation is empty.

## Scenario 6: failures and references (US2, FR-024 to FR-030, SC-007)

```bash
ANSWER_MODEL_URL=http://127.0.0.1:9/v1 docker compose up -d api --wait
```

Ask any question. The turn shows "The answer model is not responding." with "Reference:
…" under it, and a retry action. Search the logs for the reference:

```bash
docker compose logs api | grep <reference>
```

Then restore the API, retry, and confirm the answer replaces the failure while every
other turn is unchanged:

```bash
docker compose up -d api --wait
```

Stop the API with `docker compose stop api`. The connection notice appears and questions
fail with "The service could not be reached.". Start it again, and the notice clears
without a reload.

For the busy message, send many questions from a script as in scenario 9 of the question
answering quickstart and ask one from the client meanwhile. It shows the busy message
with the wait in seconds.

## Scenario 7: restrict to documents (US4, FR-038 to FR-041)

1. Type "ins" in the panel's filter and select the INSST guide. It appears next to the
   question input.
2. Ask a question. The turn shows "Restricted to insst-guia-riesgo-electrico.pdf", and
   every source and image comes from it.
3. Documents still processing cannot be selected.
4. Clear the selection. The next question uses every document.

## Scenario 8: responsiveness (SC-010)

Run `frontend/tests/e2e/long-conversation.spec.ts`, which loads 50 answered turns with
primary images from the fixtures:

```bash
npm --prefix frontend run test:e2e -- long-conversation
```

Or ask 50 questions by hand. Typing, scrolling and opening an image react without
noticeable delay.

## Scenario 9: walkthrough (SC-004, SC-005)

With the three manuals ready, give each of five people who have not used the client
these tasks, and record the time and outcome of each:

1. Ask "Why is a series wound generator never used on airplanes?" and say which document
   and page the answer comes from.
2. Open the answer's figure at full size.
3. Ask "What is the recommended tire pressure for a bicycle?" and say whether the system
   answered it.
4. Upload the welding manual from a clean system, wait until it is ready, and ask a
   question about it.

Targets:

- Every participant tells the no-information reply apart from an answer.
- At least 90% find the source and open the figure within 10 seconds of the answer
  appearing.
- At least 90% complete task 4 without instructions.

## Automated checks

```bash
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend run test:coverage
npm --prefix frontend exec -- playwright install --with-deps
npm --prefix frontend run test:e2e
uv run --directory backend pytest --cov
uv run --project backend pre-commit run --all-files
```

Expected:

- Every command passes.
- Frontend coverage is at least 90% and backend coverage stays at least 90%.
- The Playwright suite, including the axe checks, passes in Chromium, Firefox and
  WebKit.
