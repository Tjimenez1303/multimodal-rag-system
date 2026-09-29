"""Command-line entry point: ``python -m multimodal_rag {api,worker}``."""

import argparse
import asyncio
from collections.abc import Sequence

import uvicorn

from multimodal_rag.bootstrap import run_worker
from multimodal_rag.shared.config import ApiSettings


def main(argv: Sequence[str] | None = None) -> None:
    """Start the API or the worker, as selected on the command line.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            ``sys.argv[1:]``.
    """
    parser = argparse.ArgumentParser(prog="python -m multimodal_rag")
    parser.add_argument("role", choices=["api", "worker"])
    role = parser.parse_args(argv).role
    if role == "api":
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
    else:
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
