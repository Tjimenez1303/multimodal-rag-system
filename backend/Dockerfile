# Multi-stage build following the uv Docker integration guide, with non-editable
# installs so the runtime stage needs only the virtual environment.
# One image serves every backend role, and compose selects api, worker or migrate.

ARG PYTHON_IMAGE=python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

FROM ${PYTHON_IMAGE} AS builder
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
COPY pyproject.toml uv.lock ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="multimodal-rag-backend" \
    org.opencontainers.image.description="API, ingestion worker and migrations of the multimodal RAG system" \
    org.opencontainers.image.source="https://github.com/Tjimenez1303/multimodal-rag-system" \
    org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot \
    && mkdir -p /data/blobs \
    && chown nonroot:nonroot /data/blobs
COPY --from=builder --chown=nonroot:nonroot /app/.venv /app/.venv
COPY --chown=nonroot:nonroot alembic.ini /app/alembic.ini
COPY --chown=nonroot:nonroot migrations /app/migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER nonroot
CMD ["python", "-m", "multimodal_rag", "api"]
