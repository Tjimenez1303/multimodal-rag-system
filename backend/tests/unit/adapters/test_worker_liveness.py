import asyncio
from pathlib import Path

from multimodal_rag.adapters.worker.liveness import LivenessFile


def test_age_is_unknown_before_the_first_touch(tmp_path: Path) -> None:
    assert LivenessFile(tmp_path / "alive").age_seconds() is None


def test_touch_makes_the_file_fresh(tmp_path: Path) -> None:
    liveness = LivenessFile(tmp_path / "nested" / "alive")

    liveness.touch()

    age = liveness.age_seconds()
    assert age is not None
    assert age < 5


async def test_keep_alive_touches_until_stopped(tmp_path: Path) -> None:
    liveness = LivenessFile(tmp_path / "alive")
    stop = asyncio.Event()

    task = asyncio.create_task(liveness.keep_alive(stop=stop, interval_seconds=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert liveness.age_seconds() is not None
