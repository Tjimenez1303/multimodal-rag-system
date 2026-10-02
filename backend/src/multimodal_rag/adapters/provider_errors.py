"""Classification of HTTP failures of external services into provider errors.

Timeouts, connection failures, 429 and 5xx answers are transient, so the retry policy
repeats them. Any other error status is a rejected request, which repeating cannot fix.
Every adapter that reaches a service over HTTP uses these two functions.
"""

import httpx

from multimodal_rag.shared.errors import (
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_TOO_MANY_REQUESTS = 429
_FIRST_SERVER_ERROR = 500


def transport_error(error: httpx.TransportError, *, service: str) -> ProviderError:
    """Translate a failure to reach a service.

    Args:
        error: Error raised by httpx before an answer arrived.
        service: Name of the service for the message, such as ``vector index``.

    Returns:
        A timeout error for timeouts, an unavailable error otherwise.
    """
    # A timeout is reported apart from a service that cannot be reached
    if isinstance(error, httpx.TimeoutException):
        return ProviderTimeoutError(f"The {service} did not answer in time")
    return ProviderUnavailableError(f"The {service} is unreachable")


def status_error(status: int | None, *, service: str) -> ProviderError:
    """Translate an error status answered by a service.

    Args:
        status: HTTP status of the answer, or ``None`` when the client lost it.
        service: Name of the service for the message, such as ``embedding model``.

    Returns:
        An unavailable error for 429, 5xx or an unknown status, and a response
        error for any other status.
    """
    # Overload and server errors may pass, so they count as unavailable
    if status is None or status == _TOO_MANY_REQUESTS or status >= _FIRST_SERVER_ERROR:
        return ProviderUnavailableError(f"The {service} answered {status}")
    return ProviderResponseError(f"The {service} rejected the request: {status}")
