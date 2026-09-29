from collections.abc import Iterator

import pytest
import stamina

from multimodal_rag.shared.config import WorkerSettings
from multimodal_rag.shared.errors import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StorageTimeoutError,
    StorageUnavailableError,
)
from multimodal_rag.shared.resilience import RetryPolicy, call_with_retry

ATTEMPTS = 3
POLICY = RetryPolicy(
    attempts=ATTEMPTS,
    initial_wait_seconds=0.1,
    max_wait_seconds=1.0,
    jitter_seconds=0.5,
    timeout_seconds=30.0,
)


@pytest.fixture(autouse=True)
def instant_retries() -> Iterator[None]:
    stamina.set_testing(True, attempts=ATTEMPTS)
    yield
    stamina.set_testing(False)


class FlakyOperation:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "done"


async def test_transient_failures_are_retried_until_success() -> None:
    operation = FlakyOperation(
        [ProviderUnavailableError("down"), ProviderTimeoutError("slow")]
    )

    result = await call_with_retry(POLICY, operation)

    assert result == "done"
    assert operation.calls == 3


async def test_transient_failure_is_raised_after_the_last_attempt() -> None:
    operation = FlakyOperation([ProviderUnavailableError("down")] * 5)

    with pytest.raises(ProviderUnavailableError):
        await call_with_retry(POLICY, operation)

    assert operation.calls == ATTEMPTS


async def test_non_transient_failures_are_not_retried() -> None:
    operation = FlakyOperation([ProviderResponseError("bad request")])

    with pytest.raises(ProviderResponseError):
        await call_with_retry(POLICY, operation)

    assert operation.calls == 1


def test_policy_for_providers_reads_every_bound_from_settings() -> None:
    settings = WorkerSettings.model_validate(
        {
            "database_url": "postgresql+asyncpg://rag:x@db/rag",
            "blob_root": "/data/blobs",
            "qdrant_url": "http://qdrant:6333",
            "vlm_url": "http://models/v1/",
            "vlm_model": "vlm",
            "embedder_url": "http://models/v1/",
            "embedder_model": "embedder",
            "embedder_tokenizer_path": "/opt/tokenizers/embedder/tokenizer.json",
            "provider_retry_attempts": 5,
            "provider_retry_initial_wait_seconds": 0.2,
            "provider_retry_max_wait_seconds": 8,
            "provider_retry_jitter_seconds": 0.3,
            "provider_retry_timeout_seconds": 90,
        }
    )

    policy = RetryPolicy.for_providers(settings)

    assert policy == RetryPolicy(
        attempts=5,
        initial_wait_seconds=0.2,
        max_wait_seconds=8,
        jitter_seconds=0.3,
        timeout_seconds=90,
    )


async def test_only_the_given_errors_are_retried() -> None:
    operation = FlakyOperation([StorageUnavailableError("database restarting")])

    result = await call_with_retry(
        POLICY, operation, on=(StorageUnavailableError, StorageTimeoutError)
    )

    assert result == "done"
    assert operation.calls == 2


async def test_unlimited_retries_outlast_the_float_range_of_the_backoff() -> None:
    # 2.0 ** 1024 overflows a float, and stamina then waits its maximum instead.
    policy = RetryPolicy(
        attempts=None,
        initial_wait_seconds=0.000001,
        max_wait_seconds=0.000001,
        jitter_seconds=0,
        timeout_seconds=None,
    )
    operation = FlakyOperation([ProviderUnavailableError("down")] * 1_100)

    with stamina.set_testing(False):
        result = await call_with_retry(policy, operation)

    assert result == "done"
    assert operation.calls == 1_101


def test_claim_policy_retries_without_limit_from_the_poll_interval() -> None:
    settings = WorkerSettings.model_validate(
        {
            "database_url": "postgresql+asyncpg://rag:x@db/rag",
            "blob_root": "/data",
            "qdrant_url": "http://qdrant:6333",
            "vlm_url": "http://models/v1",
            "vlm_model": "vlm",
            "embedder_url": "http://models/v1",
            "embedder_model": "embedder",
            "embedder_tokenizer_path": "/opt/tokenizers/embedder/tokenizer.json",
            "poll_seconds": 2,
            "claim_retry_max_wait_seconds": 30,
            "claim_retry_jitter_seconds": 0.5,
        }
    )

    assert RetryPolicy.for_claims(settings) == RetryPolicy(
        attempts=None,
        initial_wait_seconds=2,
        max_wait_seconds=30,
        jitter_seconds=0.5,
        timeout_seconds=None,
    )
