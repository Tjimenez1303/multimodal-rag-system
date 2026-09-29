# Quickstart: Reranked Relevance Gate

This guide proves the feature end to end on the running system. The response shape is in
[contracts/openapi.yaml](contracts/openapi.yaml), and the new fields are explained in
[data-model.md](data-model.md).

## Prerequisites

- The system set up as in `specs/002-grounded-question-answering/quickstart.md`, with the
  three sample manuals ingested and the `ask` helper defined.
- The first `docker compose up` after this feature pulls `ai/qwen3-reranker:0.6B`, about
  1.2 GB, once.

## Start the system and ingest the labeled-value fixture

```bash
docker compose up -d --build --wait
curl -s -F file=@backend/tests/fixtures/labeled_total.pdf localhost:8000/api/v1/documents | jq
```

Wait until the job is `completed`. The fixture is a two-page maintenance quote with invented values whose second
page shows only "Terminos y Condiciones" and "Total Neto: $880,900.0".

## Scenario 1: labeled value asked with a few words (US1, FR-005, SC-006)

```bash
ask '{"question": "Total Neto"}' | jq '{status, answer, citations, top: .sources[0] | {document_name, pages, relevance, similarity}}'
ask '{"question": "Cual es mi total Neto"}' | jq '{status, answer, citations}'
```

Expected:

- **Status.** `answered` for both questions, with the value $880,900.0 in the answer.
- **Citation.** `labeled_total.pdf`, page 2.
- **First source.** The total's unit, with a `relevance` near 1 and a `similarity` below
  0.60, which shows the dense similarity no longer gates.

## Scenario 2: short questions over the sample manuals (US1, SC-002)

Ask one- to three-word questions whose answer a sample manual states, such as a component
name or a section title, and confirm each returns `answered` with a citation to the
expected page.

## Scenario 3: questions the documents do not answer (US2, FR-002, SC-003)

```bash
time ask '{"question": "How much does the generator cost?"}' | jq '{status, reason, sources}'
time ask '{"question": "Who wrote this manual?"}' | jq '{status, reason, sources}'
```

Expected:

- **Outcome.** `not_enough_information` with reason `no_relevant_content`, no sources and
  no image.
- **Time.** Under 2 seconds, because the answer model is not asked.

## Scenario 4: judged order (US3, FR-007, FR-008)

```bash
ask '{"question": "Why is a series wound generator never used on airplanes?"}' \
  | jq '[.sources[] | {rank, relevance, similarity, cited}]'
```

Expected: `rank` runs 1, 2, 3 and so on while `relevance` never increases, every source
carries a `relevance` between 0 and 1, and the cited sources have the highest relevance.

## Scenario 5: exact identifiers are still supplied (US1, FR-007, SC-007)

Repeat Scenario 4 of `specs/002-grounded-question-answering/quickstart.md` and confirm the
unit that holds the identifier is among `sources` even when its `relevance` is below that
of other sources, and that the answer cites its page.

## Scenario 6: reranker down (US4, FR-011, FR-012, FR-013, SC-005)

Docker Model Runner reloads an unloaded model on demand, so the outage is simulated by
pointing the API at a port where nothing listens. The Compose `models` element sets
`RERANKER_URL` over any `environment` value, so an override file replaces the API's
models with `!override` and sets the URL itself:

```bash
cat > /tmp/reranker-down.yaml <<'YAML'
services:
  api:
    models: !override
      vlm:
        endpoint_var: ANSWER_MODEL_URL
        model_var: ANSWER_MODEL
      embedder:
        endpoint_var: EMBEDDER_URL
        model_var: EMBEDDER_MODEL
    environment:
      RERANKER_URL: http://127.0.0.1:9/v1/
      RERANKER_MODEL: ai/qwen3-reranker:0.6B
YAML
docker compose -f compose.yaml -f /tmp/reranker-down.yaml up -d api --wait
time ask '{"question": "Total Neto"}' | jq '{status, code, detail}'
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' localhost:8000/api/v1/documents
docker compose up -d api --wait
```

Expected:

- **The question.** 503 `reranker_unavailable` within `ANSWER_DEADLINE_SECONDS`, after the
  configured retries, and no answer written without the ranking.
- **The library.** It answers 200 in under 2 seconds.

## Scenario 7: relevance evaluation (SC-001 to SC-004, SC-007)

```bash
uv run --directory backend python -m tests.evaluation.evaluate_relevance
docker compose logs api --no-log-prefix > /tmp/api.log
uv run --directory backend python -m tests.evaluation.evaluate_relevance --api-log /tmp/api.log
```

The second run adds the best judgement of every question, including those the gate
stopped, which return no sources and appear only in the API log.

Expected: the report shows at least 90% of answerable questions reaching the answer model,
at least 75% of the short ones, at least 70% of the unanswerable ones stopped by the gate
and at least 90% ending as not enough information overall, the identifier's unit supplied
for at least 95% of identifier questions, and the 95th percentile of the judging time under
2.5 seconds. It also prints the relevance distribution per label, which
is the evidence for any change to `MIN_RELEVANCE`.

## Automated checks

```bash
uv run --project backend pre-commit run --all-files
uv run --directory backend pytest --cov
npm --prefix frontend run typecheck
```

- **Default run.** It includes the unit tests with the fake reranker (gate, ordering,
  relevance on sources, failure mapping, cancellation), the respx tests of the reranker
  adapter (prompt, scoring, missing tokens, shortening, retries) and the contract tests of
  `askQuestion` against this feature's contract.
- **Excluded.** The relevance evaluation needs the running models, so it is not part of
  this run.
