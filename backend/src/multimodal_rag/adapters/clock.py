"""Clock adapter backed by the operating system time."""

from datetime import UTC, datetime


class SystemClock:
    """Returns the current UTC time of the host."""

    def now(self) -> datetime:
        """Return the current time with a UTC time zone."""
        return datetime.now(UTC)
