# Multi-stage build following the official uv Docker integration guide.
# The feature pull request adds the api and worker targets on top of the runtime stage.

FROM python:3.14.7-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1
WORKDIR /app
# Install dependencies first so source changes do not invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

FROM python:3.14.7-slim-trixie AS runtime
RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot
COPY --from=builder --chown=nonroot:nonroot /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
USER nonroot
CMD ["python", "-c", "import multimodal_rag"]
