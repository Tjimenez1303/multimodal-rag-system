# Quickstart: Grounded Question Answering

This guide proves the feature end to end on the running system. The request and response
shapes are in [contracts/openapi.yaml](contracts/openapi.yaml), and the fields are
explained in [data-model.md](data-model.md).

## Prerequisites

- The system set up as in `specs/001-async-pdf-ingestion/quickstart.md`, with Docker Model
  Runner enabled and `.env` created from `.env.example`.
- `curl` and `jq`.
- No new model is downloaded: the API binds the `ai/qwen3.5:9b` and
  `ai/qwen3-embedding:0.6b` models that ingestion already uses.

## Start the system and ingest the sample manuals

```bash
docker compose up -d --build --wait
```

Upload the three manuals in `docs/samples/` as in Scenario 1 of the ingestion quickstart,
and wait until each job is `completed`. Keep their document ids:

```bash
curl -s localhost:8000/api/v1/documents | jq -r '.items[] | "\(.id) \(.file_name)"'
```

A helper for the scenarios below:

```bash
ask() { curl -s -X POST localhost:8000/api/v1/questions -H 'Content-Type: application/json' -d "$1"; }
```

## Scenario 1: cited answer (US1, FR-010, FR-012, SC-001, SC-007)

```bash
time ask '{"question": "Why is a series wound generator never used on airplanes?"}' | jq '{status, answer, citations, sources: [.sources[] | {rank, document_name, pages, cited, citation_number}]}'
```

Expected:

- `status` is `answered`.
- The answer explains the poor voltage regulation and ends its statements with `[1]`.
- Citation 1 names `faa-powerplant-ch4-ignition-electrical.pdf` and page 12.
- `sources` lists 8 units, and the cited ones carry `citation_number`.
- The whole request takes less than 30 seconds, and less than 15 seconds once the model is
  loaded.

## Scenario 2: question in another language (US1, FR-019, SC-006)

```bash
ask '{"question": "¿Por qué no se usa un generador en series en los aviones?"}' | jq '{answer, citations}'
```

Expected: the answer is in Spanish and the citation still names the English manual and
page 12.

## Scenario 3: not enough information (US2, FR-006, FR-008, SC-003)

```bash
ask '{"question": "What is the best recipe for Spanish paella?"}' | jq '{status, reason, answer, citations, sources, primary_image}'
ask '{"question": "What is the torque for the cylinder head bolts of a Boeing 737 APU?"}' | jq '{status, reason, answer}'
ask '{"question": "¿Por qué no se usa un generador en series en los aviones y cuánto pesa uno?"}' | jq '{status, answer, not_covered}'
```

Expected:

- **Paella question.** `status` is `not_enough_information` and `reason` is
  `no_relevant_content`. There are no citations, no sources and no image, and the API logs
  show no call to the answer model for this request id.
- **Boeing question.** `not_enough_information`, with reason `no_relevant_content` or
  `not_answered_by_sources`.
- **Two-part question.** `answered`, and `not_covered` says in Spanish that the weight is
  not in the documents.

## Scenario 4: exact identifiers (US3, FR-004, SC-004)

```bash
ask '{"question": "What is code SPL-480?"}' | jq '{status, citations, top: .sources[0] | {pages, excerpt, low_confidence_text}}'
```

Expected: the top source is page 13 of the scanned TM manual and contains `SPL-480`. The
identifier rule lets it through the relevance gate even though its meaning similarity is
low. The scanned source may carry `low_confidence_text`.

## Scenario 5: related diagram (US4, FR-015, FR-016, SC-005)

Ask about content explained by a figure, for example:

```bash
ask '{"question": "How is a shunt generator wired?"}' | jq '{citations, primary_image, related: [.related_images[] | {page, caption}]}'
curl -s -o /tmp/primary.png "localhost:8000$(ask '{"question": "How is a shunt generator wired?"}' | jq -r .primary_image.url)" && file /tmp/primary.png
```

Expected: `primary_image` is the figure next to the cited text on the cited page, with its
caption (for example Figure 4-22). Its `url` returns a PNG. No decorative image appears.

## Scenario 6: restrict to documents (US6, FR-020)

```bash
ask "{\"question\": \"What is a shunt generator?\", \"document_ids\": [\"$INSST_ID\"]}" | jq '{status, docs: [.sources[].document_name] | unique}'
ask '{"question": "x", "document_ids": ["00000000-0000-0000-0000-000000000000"]}' | jq '{status, code, detail}'
```

Expected:

- **Restricted question.** Every source comes from the INSST guide, and the outcome is
  `not_enough_information` because the guide does not cover generators.
- **Unknown document.** 400 with code `unknown_documents`, and the detail names the id.

## Scenario 7: invalid questions (US5, FR-002)

```bash
ask '{"question": "   "}' | jq '{status, code}'
ask "{\"question\": \"$(printf 'a%.0s' {1..2001})\"}" | jq '{status, code}'
```

Expected: both are 400 with code `invalid_question`, returned at once.

## Scenario 8: answer model or search down (US5, FR-022, FR-023, FR-024, SC-008)

Docker Model Runner reloads an unloaded model on demand, so the outage is simulated by
pointing the API at a port where nothing listens:

```bash
ANSWER_MODEL_URL=http://127.0.0.1:9/v1 docker compose up -d api --wait
time ask '{"question": "What is a shunt generator?"}' | jq '{status, code, detail}'
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8000/api/v1/documents
docker compose up -d api --wait
```

Expected:

- **The question.** 503 `answer_model_unavailable` within `ANSWER_DEADLINE_SECONDS`, after
  the configured retries.
- **The library.** It answers 200 in under 2 seconds.

Repeat with `docker compose stop qdrant`. The question returns 503 `search_unavailable`,
while uploads and job status still answer. Start Qdrant again afterwards.

## Scenario 9: busy and cancellation (US5, FR-028, FR-029, SC-011)

```bash
for i in $(seq 1 16); do (ask '{"question": "What is a shunt generator?"}' | jq -c '{status, code}' &) ; done; wait
```

Expected:

- **With the defaults** (2 at once, 10 waiting): 12 questions are answered and 4 return 503
  `answering_busy` with a `Retry-After` header in under 1 second.
- **No timeouts.** No accepted question exceeds the deadline.

To check cancellation, start a question and interrupt `curl` after 2 seconds. The API logs
show the question as cancelled, and the model logs show the generation stopped:

```bash
timeout 2 curl -s -X POST localhost:8000/api/v1/questions -H 'Content-Type: application/json' -d '{"question": "What is a shunt generator?"}'
docker compose logs api --since 10s | grep -i cancel
```

## Scenario 10: reference question set (SC-001 to SC-006, SC-010)

```bash
uv run --directory backend python tests/evaluation/run_reference.py --api http://localhost:8000
```

Expected: the report shows every criterion at or above its target. It also shows the
top-similarity distribution of answerable and unanswerable questions, which is the
evidence for any change to `MIN_SIMILARITY`.

## Automated checks

```bash
uv run --project backend pre-commit run --all-files
uv run --directory backend pytest --cov
```

- **Default run.** It includes the unit tests with fakes (grounding, gate, citations, image
  selection, admission and cancellation), the contract tests for `askQuestion`, and the
  Qdrant integration tests for the similarity scores.
- **Excluded.** The reference evaluation is a script that needs the running
  models, so it is not part of this run.
