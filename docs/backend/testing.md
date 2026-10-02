# Testing the backend

The suite lives in `backend/tests/` and runs with pytest. CI fails when line and branch
coverage drops below 90%.

```bash
uv run --directory backend pytest --cov
uv run --directory backend pytest tests/unit
uv run --directory backend pytest -m "not integration"
```

The integration tests start PostgreSQL and Qdrant containers with testcontainers, so
Docker must be running. The other layers need nothing but the virtual environment.

## Test layers

| Folder | What it checks | Needs |
| --- | --- | --- |
| `unit/` | Domain rules, use cases with fakes, adapters with respx or local files. Mirrors the package: `unit/ingestion/`, `unit/answering/`, `unit/adapters/`, `unit/shared/` | Nothing |
| `contract/` | Every HTTP response validates against the OpenAPI contracts in `specs/*/contracts/`, and the API serves exactly the operations the contracts declare | Nothing |
| `integration/` | The PostgreSQL repositories and job queue, notifications, the Qdrant index, the Docling extractor, the tokenizer, crash recovery and a worker processing a real PDF end to end | Docker |
| `evaluation/` | A script that measures the relevance gate on labeled questions against a running system. Not run in CI | A running stack |
| `load/` | A script that uploads a backlog of PDFs and measures API latency. Not run in CI | A running stack |

## Fakes, not mocks

Use cases are tested with fakes that implement the ports, all in
[`tests/fakes.py`](../../backend/tests/fakes.py): `InMemoryDocumentRepository`,
`InMemoryJobQueue`, `InMemoryVectorIndex`, `FakeEmbedder`, `FakeAnswerGenerator` and the
others. `MagicMock` and `Mock` are banned by a ruff rule, because a fake that implements
the protocol keeps tests honest when a port changes. `test_fakes_match_ports.py` checks
each fake against its port.

HTTP adapters are tested with [respx](https://lundberg.github.io/respx/), which answers
httpx requests with prepared responses.

## Helpers and fixtures

| Path | Purpose |
| --- | --- |
| `tests/builders.py` | Builders of extracted elements and relationships for the ingestion rules |
| `tests/library.py` | A small indexed library for testing `AnswerQuestion` |
| `tests/fixtures/` | Test PDFs: digital, scanned, encrypted, a split table, a file that is not a PDF |
| `tests/fixtures/build_fixtures.py` | Regenerates those PDFs |

Fixtures never contain real personal data. A bug found in a real document is reproduced
with invented values.

## Writing a test

- Assert behavior through the public interface: the use case's result, the HTTP
  response, the stored rows. Avoid asserting how the code got there.
- A bug fix comes with a test that fails before the fix.
- Name tests as sentences, such as `test_a_document_being_ingested_is_kept`.
- `asyncio_mode` is `auto`, so async tests need no decorator. Warnings fail the run.
