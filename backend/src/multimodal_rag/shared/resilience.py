"""Retry policy for calls to external services.

Only transient failures are retried: an unreachable service or a timeout. Rejected
requests and invalid answers fail at once, because repeating them cannot succeed. Waits
grow exponentially with jitter so that many workers do not retry in lockstep.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Self

import stamina

from multimodal_rag.shared.config import ProviderSettings, WorkerSettings
from multimodal_rag.shared.errors import ProviderTimeoutError, ProviderUnavailableError

TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    ProviderUnavailableError,
    ProviderTimeoutError,
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How often and how patiently a transient failure is retried.

    Attributes:
        attempts: Total attempts, including the first one, or ``None`` for no limit.
        initial_wait_seconds: Wait before the second attempt, before jitter.
        max_wait_seconds: Longest wait between two attempts, jitter included.
        jitter_seconds: Largest random amount added to each wait.
        timeout_seconds: Total time budget across all attempts and waits, or
            ``None`` for no limit.
    """

    attempts: int | None
    initial_wait_seconds: float
    max_wait_seconds: float
    jitter_seconds: float
    timeout_seconds: float | None

    @classmethod
    def for_providers(cls, settings: ProviderSettings) -> Self:
        """Build the policy shared by calls to models and to the vector index.

        Args:
            settings: Settings of the API or the worker, holding the retry bounds.

        Returns:
            The policy configured by the ``PROVIDER_RETRY_*`` settings.
        """
        return cls(
            attempts=settings.provider_retry_attempts,
            initial_wait_seconds=settings.provider_retry_initial_wait_seconds,
            max_wait_seconds=settings.provider_retry_max_wait_seconds,
            jitter_seconds=settings.provider_retry_jitter_seconds,
            timeout_seconds=settings.provider_retry_timeout_seconds,
        )

    @classmethod
    def for_claims(cls, settings: WorkerSettings) -> Self:
        """Build the policy of the worker when claiming a job fails.

        The database is the worker's only source of work, so claims are retried
        until it answers again, starting at the poll interval.

        Args:
            settings: Worker settings holding the poll interval and the bounds.

        Returns:
            A policy without attempt or time limits.
        """
        return cls(
            attempts=None,
            initial_wait_seconds=settings.poll_seconds,
            max_wait_seconds=settings.claim_retry_max_wait_seconds,
            jitter_seconds=settings.claim_retry_jitter_seconds,
            timeout_seconds=None,
        )


async def call_with_retry[T](
    policy: RetryPolicy,
    operation: Callable[[], Awaitable[T]],
    *,
    on: tuple[type[Exception], ...] = TRANSIENT_ERRORS,
) -> T:
    """Run an async operation, retrying it on transient errors.

    stamina computes each wait: exponential with jitter, capped at the maximum
    wait, which it also returns once the exponential no longer fits in a float.

    Args:
        policy: Attempts and backoff bounds to apply.
        operation: Zero-argument coroutine factory that performs one attempt.
        on: Errors worth retrying. Defaults to transient provider errors.

    Returns:
        The result of the first successful attempt.

    Raises:
        Exception: One of the ``on`` errors once the attempts or the time budget
            run out, or any other error on the attempt that produced it.
    """
    async for attempt in stamina.retry_context(
        on=on,
        attempts=policy.attempts,
        timeout=policy.timeout_seconds,
        wait_initial=policy.initial_wait_seconds,
        wait_max=policy.max_wait_seconds,
        wait_jitter=policy.jitter_seconds,
    ):
        with attempt:
            return await operation()
    raise AssertionError("stamina always returns or raises")  # pragma: no cover
