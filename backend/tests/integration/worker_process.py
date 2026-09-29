"""The real ingestion worker as a separate process, with its models faked.

Run with ``python -m tests.integration.worker_process`` and the worker's environment.
respx only intercepts requests inside its own process, so this module installs the
model routes of ``model_apis`` before starting the worker. When ``HOLD_PUBLISH`` is
``1``, the request that publishes a document's units never gets an answer, so an
attempt stops right after it stored its units and elements and waits to be killed.
"""

import asyncio
import os

import httpx
import respx

from multimodal_rag import bootstrap
from tests.integration.model_apis import route_model_apis

HOLD_PUBLISH = "WORKER_PROCESS_HOLD_PUBLISH"
# Qdrant's endpoint that sets payload fields, used to make units visible.
_SET_PAYLOAD_PATH = r"^/collections/[^/]+/points/payload$"


async def _never_answer(request: httpx.Request) -> httpx.Response:
    answer: asyncio.Future[httpx.Response] = asyncio.get_running_loop().create_future()
    return await answer


def main() -> None:
    """Run the worker until SIGTERM or SIGINT, answering the model APIs locally."""
    with respx.mock(assert_all_called=False) as router:
        route_model_apis(router)
        if os.environ.get(HOLD_PUBLISH) == "1":
            router.post(path__regex=_SET_PAYLOAD_PATH).mock(side_effect=_never_answer)
        # Qdrant and, without DOCLING_ARTIFACTS_PATH, Docling's model downloads.
        router.route().pass_through()
        asyncio.run(bootstrap.run_worker())


if __name__ == "__main__":
    main()
