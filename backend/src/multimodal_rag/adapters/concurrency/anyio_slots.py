"""``AnswerSlots`` over ``anyio.CapacityLimiter``, which ships with Starlette.

The limiter holds one token per question answered at once and counts the questions
waiting for a token, so no counter is written here. A question that finds no free
token and a full waiting line is rejected at once. The check and the wait run with no
``await`` in between, so they are atomic on the event loop.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio

from multimodal_rag.answering.errors import AnsweringBusyError


class AnyioAnswerSlots:
    """Admits a bounded number of questions and lets a bounded number wait.

    Build it inside the running event loop, as the lifespan does.

    Args:
        capacity: Questions answered at the same time.
        queue_limit: Questions allowed to wait for a free place.
    """

    def __init__(self, *, capacity: int, queue_limit: int) -> None:
        self._limiter = anyio.CapacityLimiter(capacity)
        self._queue_limit = queue_limit

    @asynccontextmanager
    async def admit(self) -> AsyncGenerator[None]:
        """Hold a place for one question for the duration of a block.

        Yields:
            Nothing. The place is freed on leaving the block, also on cancellation.

        Raises:
            AnsweringBusyError: When every place is taken and the line is full.
        """
        full = self._limiter.available_tokens == 0
        if full and self._limiter.statistics().tasks_waiting >= self._queue_limit:
            raise AnsweringBusyError()
        async with self._limiter:
            yield
