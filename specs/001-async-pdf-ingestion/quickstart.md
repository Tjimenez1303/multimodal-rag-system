# Quickstart: Validate Asynchronous PDF Ingestion

This guide proves the feature works end to end once it is implemented. It relies on
the REST contract in [contracts/openapi.yaml](contracts/openapi.yaml) and the entities in
[data-model.md](data-model.md).

## Prerequisites

- Docker Desktop with at least 12 CPUs and 20 GB of memory assigned.
- About 15 GB of free disk for images and models.
- Sample documents in `docs/samples/` (git-ignored):

  | File | Pages | Type | Source |
  |---|---|---|---|
  | `faa-powerplant-ch4-ignition-electrical.pdf` | 71 | Digital, English | FAA-H-8083-32B chapter 4, US public domain |
  | `insst-guia-riesgo-electrico.pdf` | 86 | Digital, Spanish | INSST technical guide. Reuse requires citing "Origen de los datos: INSST" |
  | `tm-5-3431-201-10-welding-machine-scanned.pdf` | 65 | Scanned, English | US Army TM 5-3431-201-10, Internet Archive, Public Domain Mark |

- Docker Model Runner enabled once, so the models run on the host GPU:

  ```bash
  docker desktop enable model-runner --tcp 12434 --cors none
  ```

  On Linux, install the `docker-model-plugin` package instead.

## Start the system

```bash
cp .env.example .env
docker compose up -d
```

The first start downloads the models once (about 7.2 GB); `docker compose up` does it
before starting the worker. Wait until the API reports ready:

```bash
docker compose ps
curl -s http://localhost:8000/health/ready
```

On a machine without Docker Model Runner, start with the Ollama fallback instead. It
runs the models on CPU, so figure descriptions are several times slower:

```bash
docker compose -f compose.yaml -f compose.ollama.yaml up -d
```

## Scenario 1: upload and follow a digital manual (US1, SC-001, SC-002, SC-003)

```bash
curl -s -w '\n%{time_total}s\n' -F file=@docs/samples/faa-powerplant-ch4-ignition-electrical.pdf \
  http://localhost:8000/api/v1/documents
```

Expected:

- Status 202, with a `job_id` and a `document_id`.
- The total time printed by curl is under 2 seconds.

Poll the job:

```bash
curl -s http://localhost:8000/api/v1/jobs/<job_id>
```

Expected:

- `status` goes from `pending` to `processing` to `completed`.
- While processing, the job shows `stage`, `pages_done` and `pages_total`.
- When completed, `summary` counts pages, tables, images and retrieval units.
- The time from `started_at` to `finished_at`, minus figure descriptions, is under
  4 minutes per 100 pages.

## Scenario 2: captured elements (US2, SC-004, SC-005, SC-012)

```bash
curl -s "http://localhost:8000/api/v1/documents/<document_id>/elements?kind=image&limit=5"
curl -s -o figure.png http://localhost:8000/api/v1/documents/<document_id>/images/<element_id>
```

Expected:

- Every element has `page` and a `bbox` with `origin: top_left`.
- Images carry `labels`, a `description` and a `description_status`.
- Decorative images are `skipped`.
- The PNG opens and shows the figure.

## Scenario 3: scanned manual (FR-022, FR-023, SC-010)

Upload `tm-5-3431-201-10-welding-machine-scanned.pdf`.

Expected:

- The job completes.
- Text elements have `origin: recognized` with a `confidence`.
- `summary.recognized_pages` equals the number of scanned pages.
- The lubrication table that continues across pages shows a `continues` relationship.

## Scenario 4: identical upload and rejections (FR-002, FR-016)

- Upload the same FAA file again. Expected: status 200, the same `document_id` and
  `job_id`, and `already_ingested: true`.
- Upload a text file renamed to `.pdf`. Expected: 415 problem details with
  `code: unsupported_media_type`.
- Upload a file over the size limit. Expected: 413 with `code: file_too_large`.

## Scenario 5: crash recovery (US3, FR-025, SC-008)

While the Spanish guide is processing, kill the worker hard:

```bash
docker compose kill -s SIGKILL worker && docker compose up -d worker
```

Expected:

- Within the lease duration plus the polling interval, the job is processing again with
  `attempt: 2`.
- It then completes, and its retrieval unit count equals the count from a clean run
  (no duplicates).

## Scenario 6: vision model unavailable (FR-027)

Point the worker at an unreachable vision model, then upload a document:

```bash
VLM_URL=http://127.0.0.1:9/v1 docker compose up -d worker
```

Expected:

- The job completes.
- Figures show `description_status: not_described`.
- The summary reports how many figures lack a description.

## Scenario 7: bulk load (US3, SC-006)

Upload 100 copies with distinct bytes, for example by appending a PDF comment with a
counter to each copy, while measuring upload and status latency.

Expected:

- p95 latency stays under 2 seconds for uploads and status checks.
- Adding worker replicas shortens the total time:

  ```bash
  docker compose up -d --scale worker=2
  ```

## Automated checks

```bash
cd backend
uv run pytest --cov
uv run lint-imports
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Expected: every check passes, coverage is at least 90%, and the import contracts are kept.
