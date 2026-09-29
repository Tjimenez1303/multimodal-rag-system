# 0003. Local models served by Docker Model Runner

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Ingestion needs two models: one that describes each diagram in words, so it can be found
by meaning, and one that turns text into vectors for search. Documents must never leave
the machine, there is no budget for paid APIs, and a reviewer must start the whole
system with one command. On a Mac, containers cannot use the graphics processor, and
without it the models are too slow for the time targets.

Which models run, and where?

## Decision drivers

- Describing a figure adds at most 8 seconds on average (SC-011).
- A 100-page digital manual completes in under 4 minutes without descriptions (SC-003).
- Everything runs locally with open licenses.
- One start command, with the models downloaded automatically.
- Replacing the model provider must not change the application.

## Considered options

1. Docker Model Runner on the host graphics processor, declared in Compose.
2. Ollama inside a container.
3. Ollama installed on the host.

## Decision outcome

Chosen option: **Docker Model Runner**, serving `ai/qwen3.5:9b` for figure descriptions
and `ai/qwen3-embedding:0.6b` for embeddings. Compose declares both models, downloads
them on the first start and hands their addresses to the worker. The worker talks to
them through the widely supported OpenAI-compatible interface, so Ollama or another
provider only needs a different address and model name.

### Consequences

- Good, because descriptions take 6.0 seconds per figure on digital pages and embeddings
  run ten times faster than on container CPU, which meets SC-003 and SC-011.
- Good, because `docker compose up` starts everything and downloads about 7.2 GB of models once.
- Bad, because Docker Model Runner must be enabled once per machine, and on Linux it
  needs a separate package.
- Bad, because every worker shares the same graphics processor, so adding workers does
  not make figure descriptions faster.
- Neutral, because a machine without Docker Model Runner can still use Ollama by
  changing the model addresses and names, at several times the processing time.

## Annex: technical evidence

### Measurements on the reference machine

Apple M4 Pro, Docker Desktop with 12 CPUs and 20 GB, 2026-09-28 and 2026-09-29.

| Model and runtime | Workload | Result |
|---|---|---|
| `qwen3.5:9b`, Ollama in container (CPU) | 18 figures | 34.7 s per figure |
| `qwen3.5:9b`, DMR on Metal | 17 figures | 8.5 s per figure |
| `qwen3.5:9b`, DMR, 2 in parallel | 16 digital figures | 6.0 s per figure effective |
| `qwen3.5:9b`, DMR, 4 in parallel | 16 digital figures | 7.0 s per figure effective, GPU saturated |
| `qwen3-embedding:0.6b`, Ollama in container | 256 passages | 2.6 passages per second |
| `qwen3-embedding:0.6b`, DMR on Metal | 256 passages | 25.9 passages per second |

| Full pipeline, one worker | Minutes | Figures described | Retrieval units |
|---|---|---|---|
| FAA (71 pages) | 11.5 | 100 | 309 |
| INSST (86 pages) | 6.5 | 34 | 309 |
| TM scanned (65 pages) | 8.7 | 31 | 173 |

Two workers ran 4 FAA copies without descriptions in 7 min 1 s against 8 min 26 s for
one worker: two extractions saturate the 12 CPUs of the Docker VM. With descriptions the
shared GPU bounds the gain at about 1.15 times.

### Model choice

Qwen3.5-9B (Apache 2.0) leads its size class on OCRBench (89.2) and OmniDocBench 1.5
(87.7) and supports 201 languages. Newer Qwen releases publish no small sizes.
Qwen3-Embedding-0.6B (Apache 2.0, 1024 dimensions) scores 64.65 on MTEB multilingual
retrieval. The embedding model runs with a physical batch of 2048 tokens, because
llama.cpp returned HTTP 500 on inputs above the default 512. Thinking is turned off both
in the model flags and on every request.

### Sources

- https://docs.docker.com/ai/model-runner/
- https://docs.docker.com/compose/how-tos/models-and-compose/
- https://huggingface.co/Qwen/Qwen3.5-9B
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://docs.ollama.com/faq
- Full analysis: `specs/001-async-pdf-ingestion/research.md`, sections 10, 11, 13, 15
  and 16
