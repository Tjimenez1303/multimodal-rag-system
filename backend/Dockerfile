# Multi-stage build following the uv Docker integration guide, with non-editable
# installs so the runtime stage needs only the virtual environment.
# One image serves every backend role, and compose selects api, worker or migrate with
# its command. The extraction models are baked in, so the worker needs no download.

ARG PYTHON_IMAGE=python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

# RapidOCR depends on the full opencv-python build, which links X11, GL and GLib at
# import time even without a display.
# Docling's parser renders pages with system fonts in place of the standard PDF fonts
# (Helvetica, Times, Courier) that files do not embed. Without any, it draws every
# glyph as a box, which spoils page images, figure crops and layout detection. The URW
# base 35 fonts are the free clones of those fonts.
FROM ${PYTHON_IMAGE} AS base
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libgl1 libglib2.0-0t64 libice6 libsm6 libx11-6 libxcb1 libxext6 \
        fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS dependencies
COPY --from=ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1
WORKDIR /app

# Dependencies get their own layer so source changes do not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Extraction models are downloaded once at build time, as docling-serve does, so the
# worker starts offline. The stage depends only on the dependencies and on the model
# list that CI shares, not on the source.
FROM dependencies AS models
RUN --mount=type=bind,source=docling_models.txt,target=/tmp/docling_models.txt \
    /app/.venv/bin/docling-tools models download $(cat /tmp/docling_models.txt) \
    --output-dir /opt/docling-models

# The embedding model's tokenizer sizes retrieval units and truncates embedding inputs.
# It comes from the pinned revision in the list that CI shares, like the models above.
FROM dependencies AS tokenizer
RUN --mount=type=bind,source=embedder_tokenizer.txt,target=/tmp/embedder_tokenizer.txt \
    /app/.venv/bin/hf download $(cat /tmp/embedder_tokenizer.txt) \
    --local-dir /opt/tokenizers/embedder

FROM dependencies AS builder
COPY pyproject.toml uv.lock ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM base AS runtime

LABEL org.opencontainers.image.title="multimodal-rag-backend" \
    org.opencontainers.image.description="API, ingestion worker and migrations of the multimodal RAG system" \
    org.opencontainers.image.source="https://github.com/Tjimenez1303/multimodal-rag-system" \
    org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot \
    && mkdir -p /data/blobs \
    && chown nonroot:nonroot /data/blobs
COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --from=models --chown=nonroot:nonroot /opt/docling-models /opt/docling-models
COPY --from=tokenizer --chown=nonroot:nonroot \
    /opt/tokenizers/embedder/tokenizer.json /opt/tokenizers/embedder/tokenizer.json
COPY --chown=nonroot:nonroot alembic.ini /app/alembic.ini
COPY --chown=nonroot:nonroot migrations /app/migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DOCLING_ARTIFACTS_PATH=/opt/docling-models \
    EMBEDDER_TOKENIZER_PATH=/opt/tokenizers/embedder/tokenizer.json
WORKDIR /app
USER nonroot
CMD ["python", "-m", "multimodal_rag", "api"]
