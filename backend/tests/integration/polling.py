"""Waiting for state that another process or task changes."""

import asyncio
from collections.abc import Awaitable, Callable


async def poll[T](
    probe: Callable[[], Awaitable[T | None]], *, interval: float = 0.2
) -> T:
    """Call ``probe`` until it returns something other than ``None``.

    The state lives in another process or service, so no in-process event can
    signal it. Callers bound the wait with ``asyncio.timeout``.

    Args:
        probe: Reads the state and returns ``None`` while it is not reached yet.
        interval: Pause between two probes, in seconds.

    Returns:
        The first value ``probe`` returned that is not ``None``.
    """
    while True:
        result = await probe()
        if result is not None:
            return result
        await asyncio.sleep(interval)
