"""Command-line entry point: ``python -m multimodal_rag {api,worker,worker-health}``."""

import argparse
import asyncio
import sys
from collections.abc import Sequence

import uvicorn

from multimodal_rag.bootstrap import run_worker, worker_is_alive
from multimodal_rag.shared.config import ApiSettings


def main(argv: Sequence[str] | None = None) -> None:
    """Start the API or the worker, or check the worker's health.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            ``sys.argv[1:]``.
    """
    # Read which process to run from the command line
    parser = argparse.ArgumentParser(prog="python -m multimodal_rag")
    parser.add_argument("role", choices=["api", "worker", "worker-health"])
    role = parser.parse_args(argv).role
    if role == "api":
        # Serve the REST API, building the app through the composition root
        settings = ApiSettings.load()
        # log_config=None keeps uvicorn's records on the JSON root handler, and the
        # request context middleware writes the per-request line instead of uvicorn.
        uvicorn.run(
            "multimodal_rag.bootstrap:create_api_app",
            factory=True,
            host=settings.api_host,
            port=settings.api_port,
            log_config=None,
            access_log=False,
            proxy_headers=False,
        )
    elif role == "worker":
        # Run the ingestion worker until it is told to stop
        asyncio.run(run_worker())
    else:
        # Healthcheck: exit 0 when the worker is alive, 1 otherwise
        sys.exit(0 if worker_is_alive() else 1)


if __name__ == "__main__":
    main()
