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
- Images carry `labels`, a `description` and a `description_status`, and list their
  `caption_of` and `near` relationships.
- Decorative images are `skipped`.
- The PNG opens and shows the figure.

Upload `backend/tests/fixtures/split_table.pdf` and list its tables:

```bash
curl -s "http://localhost:8000/api/v1/documents/<document_id>/elements?kind=table"
```

Expected: the table on page 2 has a `continues` relationship to the table on page 1, and
`summary.table_chains` is 1.

## Scenario 3: scanned manual (FR-022, FR-023, SC-010)

Upload `tm-5-3431-201-10-welding-machine-scanned.pdf`.

Expected:

- The job completes.
- Text elements have `origin: recognized` with a `confidence`.
- `summary.recognized_pages` equals the number of scanned pages.
- Figures carry labels recognized inside them, and the Google digitization marks are
  `skipped` as decorative.

## Scenario 4: identical upload and rejections (FR-002, FR-016)

- Upload the same FAA file again. Expected: status 200, the same `document_id` and
  `job_id`, and `already_ingested: true`.
- Upload a text file renamed to `.pdf`. Expected: 415 problem details with
  `code: unsupported_media_type`.
- Upload a file over the size limit. Expected: 413 with `code: file_too_large`.

## Scenario 5: crash recovery (US3, FR-025, SC-008)

A clean run of the Spanish guide is the reference: note its `summary.retrieval_units`.
Upload a byte-distinct copy, so it is a new document, and follow its job:

```bash
cp docs/samples/insst-guia-riesgo-electrico.pdf /tmp/insst-crash.pdf
printf '\n%%crash-test\n' >> /tmp/insst-crash.pdf
curl -s -F file=@/tmp/insst-crash.pdf http://localhost:8000/api/v1/documents
```

While the job is in `stage: describing_figures`, which lasts minutes, kill the worker
hard and count the document's points:

```bash
docker compose kill -s SIGKILL worker
docker compose exec -T -e DOC=<document_id> api python -c '
import os
from qdrant_client import QdrantClient, models
client = QdrantClient(url="http://qdrant:6333")
for visible in (False, True):
    match = [models.FieldCondition(key=k, match=models.MatchValue(value=v))
             for k, v in (("document_id", os.environ["DOC"]), ("visible", visible))]
    count = client.count("retrieval_units", count_filter=models.Filter(must=match))
    print("visible" if visible else "hidden", count.count)
'
docker compose up -d worker
```

Expected:

- Right after the kill, the document has no visible points.
- Once the lease expires (up to `LEASE_SECONDS`, 90 s, after the last heartbeat), the
  new worker claims the job, which stays `processing` with `attempt: 2`.
- The job completes with the same `retrieval_units` as the clean run. Counting again
  gives exactly that many visible points and no hidden ones.

Indexing lasts under a second, too short to hit by hand, so this scenario kills the
worker before any unit is written. The automated version,
`backend/tests/integration/test_crash_recovery.py`, kills it after the units and
elements are stored, the most partial state an attempt can leave.

## Scenario 6: vision model unavailable (FR-027)

Point the worker at an unreachable vision model, then upload a document:

```bash
VLM_URL=http://127.0.0.1:9/v1 docker compose up -d worker
```

Expected:

- The job completes.
- Figures show `description_status: not_described`.
- The summary reports how many figures lack a description.

## Scenario 7: bulk load (US3, SC-006, FR-020)

Both measurements run in a separate Compose project on port 8001 and remove it at the
end, so the development stack keeps its data. The load script uploads byte-distinct
copies of a sample and prints p50, p95, maximum, timeouts and failures per phase.

**Latency with 100 documents queued (SC-006).** The FAA chapter is the largest sample,
so it is the slowest upload:

```bash
API_PUBLISHED_PORT=8001 docker compose -p multimodal-rag-load up -d --wait
uv run --directory backend python -m tests.load.upload_backlog \
  ../docs/samples/faa-powerplant-ch4-ignition-electrical.pdf \
  --base-url http://127.0.0.1:8001 --copies 100
docker compose -p multimodal-rag-load down -v
```

Expected: every phase reports p95 under 2 seconds and no timeouts, and the probe
uploads, made with the backlog queued, stay close to the baseline uploads.

**Replicas.** Extraction runs on CPU and scales with replicas, while both models share
the host GPU (research §16). Figure descriptions are disabled so the comparison
measures the stage that scales. Run the same batch with one worker and then with two:

```bash
export API_PUBLISHED_PORT=8001 FIGURE_DESCRIPTION_ENABLED=false
docker compose -p multimodal-rag-load up -d --wait
uv run --directory backend python -m tests.load.upload_backlog \
  ../docs/samples/faa-powerplant-ch4-ignition-electrical.pdf \
  --base-url http://127.0.0.1:8001 --copies 4 --baseline 0 --probe-uploads 0 \
  --status-seconds 0 --wait
docker compose -p multimodal-rag-load up -d --wait --scale worker=2
uv run --directory backend python -m tests.load.upload_backlog \
  ../docs/samples/faa-powerplant-ch4-ignition-electrical.pdf \
  --base-url http://127.0.0.1:8001 --copies 4 --baseline 0 --probe-uploads 0 \
  --status-seconds 0 --wait
docker compose -p multimodal-rag-load down -v
unset API_PUBLISHED_PORT FIGURE_DESCRIPTION_ENABLED
```

Expected: the total processing time with two workers is shorter than with one. On the
reference machine it drops from 8 min 26 s to 7 min 1 s, because two extractions
saturate the Docker VM's CPUs (research §15). A later `docker compose up` without
`--scale` returns to one worker.

## Automated checks

```bash
cd backend
uv run pytest --cov
uv run lint-imports
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Expected: every check passes, coverage is at least 90%, and the import contracts are kept.
