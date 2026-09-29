import asyncio

import pytest

from multimodal_rag.adapters.concurrency.anyio_slots import AnyioAnswerSlots
from multimodal_rag.answering.errors import AnsweringBusyError


class Holder:
    """Takes a place and keeps it until released."""

    def __init__(self, slots: AnyioAnswerSlots) -> None:
        self.slots = slots
        self.release = asyncio.Event()
        self.admitted = asyncio.Event()

    async def __call__(self) -> None:
        async with self.slots.admit():
            self.admitted.set()
            await self.release.wait()


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_question_beyond_the_line_is_rejected_while_the_line_waits() -> None:
    slots = AnyioAnswerSlots(capacity=1, queue_limit=1)
    first, second = Holder(slots), Holder(slots)
    running = asyncio.create_task(first())
    await settle()
    waiting = asyncio.create_task(second())
    await settle()

    with pytest.raises(AnsweringBusyError):
        async with slots.admit():
            pass

    assert first.admitted.is_set() and not second.admitted.is_set()
    first.release.set()
    await asyncio.wait_for(second.admitted.wait(), timeout=1)
    second.release.set()
    await asyncio.gather(running, waiting)


async def test_a_cancelled_waiter_frees_its_place_in_the_line() -> None:
    slots = AnyioAnswerSlots(capacity=1, queue_limit=1)
    first, second, third = Holder(slots), Holder(slots), Holder(slots)
    running = asyncio.create_task(first())
    await settle()
    waiting = asyncio.create_task(second())
    await settle()

    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    replacement = asyncio.create_task(third())
    await settle()

    assert not replacement.done()
    first.release.set()
    await asyncio.wait_for(third.admitted.wait(), timeout=1)
    third.release.set()
    await asyncio.gather(running, replacement)


async def test_a_cancelled_holder_releases_its_place() -> None:
    slots = AnyioAnswerSlots(capacity=1, queue_limit=0)
    holder = Holder(slots)
    running = asyncio.create_task(holder())
    await settle()

    running.cancel()
    await asyncio.gather(running, return_exceptions=True)

    async with asyncio.timeout(1):
        async with slots.admit():
            pass


async def test_places_are_given_up_to_the_capacity() -> None:
    slots = AnyioAnswerSlots(capacity=2, queue_limit=0)
    first, second = Holder(slots), Holder(slots)
    tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
    await settle()

    assert first.admitted.is_set() and second.admitted.is_set()
    with pytest.raises(AnsweringBusyError):
        async with slots.admit():
            pass
    first.release.set()
    second.release.set()
    await asyncio.gather(*tasks)
