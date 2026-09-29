"""Cancellation of a request's work when its client disconnects.

A regular FastAPI endpoint keeps running after the client leaves. Once the body has
been read, ``receive()`` blocks until ``http.disconnect``, so a listener next to the
work can cancel it, the pattern Starlette's ``StreamingResponse`` uses. Cancelling the
work closes the answer model's HTTP request, which stops the generation, and frees the
question's place.
"""

import logging
from collections.abc import Awaitable, Callable

import anyio
from starlette.requests import Request

logger = logging.getLogger(__name__)


async def run_until_disconnect[T](
    request: Request, operation: Callable[[], Awaitable[T]]
) -> T | None:
    """Run an operation unless the client disconnects first.

    Args:
        request: Request whose body has already been read.
        operation: Work to run, such as answering the question.

    Returns:
        The result of the operation, or ``None`` when the client disconnected and the
        operation was cancelled.

    Raises:
        Exception: The error the operation raised, as itself, so the problem details
            handlers map it.
    """
    results: list[T] = []
    try:
        await _race(request, operation, results)
    except BaseExceptionGroup as failure:
        # The task group wraps the operation's error in a group that no handler maps.
        if len(failure.exceptions) == 1:
            error = failure.exceptions[0]
            raise error from error.__cause__
        raise
    return results[0] if results else None


async def _race[T](
    request: Request, operation: Callable[[], Awaitable[T]], results: list[T]
) -> None:
    async with anyio.create_task_group() as group:

        async def run() -> None:
            results.append(await operation())
            group.cancel_scope.cancel()

        async def listen() -> None:
            while (await request.receive())["type"] != "http.disconnect":
                pass
            logger.info("client disconnected, the request was cancelled")
            group.cancel_scope.cancel()

        group.start_soon(run)
        group.start_soon(listen)
