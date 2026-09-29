"""JSON requests to a server that implements the OpenAI API format.

Answers are validated against pydantic models of the documented response bodies, so a
body of the wrong shape surfaces as a rejected request with the offending field.
"""

import logging
from typing import Any

import httpx
import pydantic

from multimodal_rag.adapters.provider_errors import status_error, transport_error
from multimodal_rag.shared.errors import ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)


async def post_json[M: pydantic.BaseModel](
    client: httpx.AsyncClient,
    path: str,
    payload: dict[str, Any],
    *,
    answer: type[M],
    service: str,
    retry: RetryPolicy,
) -> M:
    """Send a JSON request and return its validated answer.

    Args:
        client: Client configured with the server's base URL and timeout.
        path: Path relative to the base URL, such as ``embeddings``.
        payload: Request body.
        answer: Model of the expected response body.
        service: Name of the service for error messages, such as ``vision model``.
        retry: Retry policy for transient failures.

    Returns:
        The response body validated against ``answer``.

    Raises:
        ProviderTimeoutError: If the server keeps timing out after the retries.
        ProviderUnavailableError: If the server stays unreachable or overloaded.
        ProviderResponseError: If the server rejects the request or answers with a
            body that does not match ``answer``.
    """

    async def attempt() -> M:
        try:
            response = await client.post(path, json=payload)
        except httpx.TransportError as error:
            raise transport_error(error, service=service) from error
        if response.is_error:
            logger.warning("%s answered status %s", service, response.status_code)
            raise status_error(response.status_code, service=service)
        try:
            return answer.model_validate_json(response.content)
        except pydantic.ValidationError as error:
            raise ProviderResponseError(
                f"The {service} answered an unexpected body"
            ) from error

    return await call_with_retry(retry, attempt)
