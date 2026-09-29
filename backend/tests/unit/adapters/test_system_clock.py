from datetime import UTC, datetime

from multimodal_rag.adapters.clock import SystemClock


def test_system_clock_returns_aware_utc_time() -> None:
    before = datetime.now(UTC)

    now = SystemClock().now()

    assert now.tzinfo is UTC
    assert before <= now <= datetime.now(UTC)
