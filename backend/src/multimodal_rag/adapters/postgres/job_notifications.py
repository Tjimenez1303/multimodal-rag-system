"""Wake-ups for idle workers through PostgreSQL ``LISTEN``.

The listener holds its own asyncpg connection outside the SQLAlchemy pool, because a
pooled connection can be recycled or reset while it listens. A notification only means
"claim now": the worker still polls at a fixed interval, so a lost connection or a
missed notification delays a job by at most one interval.
"""

import asyncio
import logging

import asyncpg
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

# Channel notified by the trigger on ingestion_jobs inserts (migration 0001).
CHANNEL = "ingestion_jobs"
_CONNECTION_ERRORS = (
    OSError,
    TimeoutError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


class PostgresJobNotifications:
    """Signals that a job was enqueued.

    Args:
        database_url: SQLAlchemy URL of the database, using asyncpg.
        timeout_seconds: Maximum time to connect and to run each listener command.
        channel: Channel to listen on, the one the enqueue trigger notifies.
    """

    def __init__(
        self, database_url: str, *, timeout_seconds: float, channel: str = CHANNEL
    ) -> None:
        self._dsn = (
            make_url(database_url)
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        self._timeout = timeout_seconds
        self._channel = channel
        self._connection: asyncpg.Connection | None = None
        self._notified = asyncio.Event()
        self._degraded = False

    async def wait(self) -> None:
        """Return when a job is enqueued. Callers bound the wait with a timeout.

        The first call after (re)connecting returns at once, because jobs enqueued
        while the connection was down sent no notification.
        """
        await self._ensure_listening()
        await self._notified.wait()
        self._notified.clear()

    async def close(self) -> None:
        """Stop listening and drop the connection.

        The connection only listens, so nothing is pending on it, and terminating it
        cannot fail and hide the error that ended the worker.
        """
        connection, self._connection = self._connection, None
        if connection is not None and not connection.is_closed():
            connection.terminate()

    async def _ensure_listening(self) -> None:
        if self._connection is not None and not self._connection.is_closed():
            return
        try:
            connection = await asyncpg.connect(
                self._dsn, timeout=self._timeout, command_timeout=self._timeout
            )
        except _CONNECTION_ERRORS as error:
            self._degrade(error)
            return
        try:
            await connection.add_listener(self._channel, self._on_notification)
        except _CONNECTION_ERRORS as error:
            # Never keep a connection that does not listen, or each retry leaks one.
            connection.terminate()
            self._degrade(error)
            return
        if self._degraded or self._connection is not None:
            logger.info("job notifications restored")
        self._connection = connection
        self._degraded = False
        self._notified.set()

    def _degrade(self, error: BaseException) -> None:
        if not self._degraded:
            logger.warning(
                "job notifications unavailable, polling only: %s", type(error).__name__
            )
        self._degraded = True

    def _on_notification(
        self, connection: object, pid: int, channel: str, payload: object
    ) -> None:
        self._notified.set()
