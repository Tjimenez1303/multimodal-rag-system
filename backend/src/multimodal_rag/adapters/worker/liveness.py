"""Liveness signal of the worker, which serves no HTTP endpoint to probe."""

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class LivenessFile:
    """A file whose modification time proves the worker's event loop is running.

    The worker touches the file at a fixed interval, and the container healthcheck
    reports the worker unhealthy when the file is older than a few intervals. A frozen
    or crashed loop stops touching the file, so the orchestrator notices it.

    Args:
        path: Location of the file, inside the worker's container.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def touch(self) -> None:
        """Record that the worker is alive now."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()

    def age_seconds(self) -> float | None:
        """Return the seconds since the last touch, or ``None`` if never touched."""
        try:
            return time.time() - self._path.stat().st_mtime
        except FileNotFoundError:
            return None

    async def keep_alive(self, *, stop: asyncio.Event, interval_seconds: float) -> None:
        """Touch the file every interval until ``stop`` is set.

        Args:
            stop: Event that ends the loop.
            interval_seconds: Seconds between two touches.
        """
        # Touch the file, then sleep until the next interval or until stopped
        while not stop.is_set():
            self.touch()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
        logger.info("liveness signal stopped")
