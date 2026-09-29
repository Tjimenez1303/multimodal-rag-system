# Multimodal RAG System

[![CI](https://github.com/Tjimenez1303/multimodal-rag-system/actions/workflows/ci.yml/badge.svg)](https://github.com/Tjimenez1303/multimodal-rag-system/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14-3776AB.svg)](https://www.python.org/downloads/)

Ask questions about technical PDF manuals and get answers that cite the page they come
from, next to the diagram they refer to.

Technical manuals mix running text with tables, wiring diagrams, exploded views and
scanned pages. This project reads all of it, keeps track of where every piece sits on
its page, and indexes it so an answer can point back to the right page and figure. It
runs entirely on your machine, including the models.

The first release covers document ingestion. Question answering and the chat client
are under development.

## Features

- Uploads return a job id right away, while a separate worker processes the document
  in the background.
- Every job reports its stage and page progress. A job interrupted by a crash is
  picked up again automatically, with up to three attempts in total.
- Text, tables and images are extracted with their page and position. Scanned pages
  go through text recognition in English and Spanish.
- A local vision model describes each relevant diagram, so a figure can be found by
  what it shows or by a label printed inside it.
- Content is split along headings, tables and figures, never in the middle of a
  sentence or a table. Tables that continue on the next page stay together.
- Every unit is indexed for both semantic and exact keyword search, which matters for
  part numbers and valve codes.

## Architecture

![Architecture of the ingestion service](docs/images/architecture.drawio.svg)

The API accepts uploads and answers status queries. Heavy work happens in the worker,
which you can scale out with more replicas. PostgreSQL stores documents and extracted
elements and also acts as the job queue. Qdrant holds the searchable units, and Docker
Model Runner serves both models on the host GPU.

The diagram is an editable draw.io file. Open it in [draw.io](https://app.diagrams.net)
to change it.

## Requirements

- Docker Desktop with at least 12 CPUs and 20 GB of memory, and about 15 GB of free
  disk for images and models
- Docker Model Runner, enabled once per machine:

  ```bash
  docker desktop enable model-runner --tcp 12434 --cors none
  ```

  On Linux, install the `docker-model-plugin` package instead.
- [uv](https://docs.astral.sh/uv/) if you want to run the tests

## Getting started

Clone the repository and start the stack:

```bash
git clone https://github.com/Tjimenez1303/multimodal-rag-system.git
cd multimodal-rag-system
cp .env.example .env
docker compose up -d --build --wait
```

The first start builds the image and downloads the models, about 7.2 GB in total. When
it finishes, the API is available at http://localhost:8000 and its interactive
documentation at http://localhost:8000/docs.

Upload a manual and follow its progress:

```bash
curl -F file=@manual.pdf http://localhost:8000/api/v1/documents
curl http://localhost:8000/api/v1/jobs/<job_id>
```

The upload answers with a `job_id` and a `document_id`. The job moves from `pending` to
`processing` to `completed`, and a completed job includes a summary of what was
captured.

## Usage

| Endpoint | Description |
|---|---|
| `POST /api/v1/documents` | Upload a PDF. Uploading the same file twice returns the existing document |
| `GET /api/v1/jobs/{job_id}` | State, stage, page progress and summary of a job |
| `GET /api/v1/documents` | Document library, newest first, with the latest job of each document |
| `GET /api/v1/documents/{document_id}` | One document and its latest job |
| `GET /api/v1/documents/{document_id}/elements` | Extracted text, tables and images, filterable by page and kind |
| `GET /api/v1/documents/{document_id}/images/{element_id}` | The image of a figure |

Every setting lives in [`.env.example`](.env.example) with its default. Two you will
probably want:

- `FIGURE_DESCRIPTION_ENABLED=false` skips the vision model, which makes ingestion
  several times faster.
- `docker compose up -d --scale worker=2` adds a second worker.

To stop the stack, run `docker compose down`. Add `-v` to delete the stored data as
well.

## Sample documents

These three public manuals were used to test and measure the system. Download them to
try it out:

| Document | Pages | Language | License |
|---|---|---|---|
| [FAA-H-8083-32B, Chapter 4: Engine Ignition and Electrical Systems](https://www.faa.gov/sites/faa.gov/files/06_amtp_ch4.pdf) | 71 | English | US public domain |
| [INSST, Guía técnica para la evaluación y prevención del riesgo eléctrico](https://www.insst.es/documentacion/catalogo-de-publicaciones/guia-tecnica-para-la-evaluacion-y-prevencion-de-los-riesgos-relacionados-con-la-proteccion-frente-al-riesgo-electrico) | 86 | Spanish | Free reuse citing the source |
| [US Army TM 5-3431-201-10, Welding Machine operator's manual](https://archive.org/details/TM5-3431-201-10) | 65, scanned | English | Public Domain Mark |

On an Apple M4 Pro, ingesting them with figure descriptions took 11.5, 6.5 and 8.7
minutes. Without descriptions a digital page takes about 1.5 seconds and a scanned page
about 3 seconds.

## Development

The backend is a Python 3.14 project managed with uv. From the repository root:

```bash
uv sync --project backend
uv run --project backend pre-commit install
```

Run the checks and the tests:

```bash
uv run --project backend pre-commit run --all-files
uv run --directory backend pytest --cov
```

The pre-commit hooks run ruff, mypy in strict mode, typos and the import boundary
checks. The test suite needs Docker running, because the integration tests start
PostgreSQL and Qdrant with testcontainers. CI runs the same commands and fails below 90%
coverage.

## Design decisions

Each major decision has a record in [`docs/adr`](docs/adr):

1. [PostgreSQL as the ingestion job queue](docs/adr/0001-postgres-job-queue.md)
2. [Document extraction with Docling](docs/adr/0002-document-extraction-with-docling.md)
3. [Local models served by Docker Model Runner](docs/adr/0003-local-models-on-docker-model-runner.md)
4. [Structure-aware retrieval units](docs/adr/0004-structure-aware-retrieval-units.md),
   which describes the chunking strategy

The stack is FastAPI, SQLAlchemy with asyncpg, PostgreSQL 18, Qdrant 1.19 with
server-side BM25, Docling 2.130, and the Qwen3.5 9B and Qwen3 Embedding 0.6B models.
The full specification, research notes and validation scenarios are in
[`specs/001-async-pdf-ingestion`](specs/001-async-pdf-ingestion).

## Contributing

Read [AGENTS.md](AGENTS.md) before opening a pull request. It covers the workflow, the
code conventions and the commit format.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Acknowledgements

- Origen de los datos: INSST, for the electrical risk guide used in testing.
- [Docling](https://github.com/docling-project/docling) for layout-aware PDF extraction.
- [Qwen](https://github.com/QwenLM) for the vision and embedding models.
