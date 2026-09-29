import asyncio
import json
from typing import Any

from starlette.types import Message

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.dependencies import provide_answer_question
from multimodal_rag.adapters.http.request_context import RequestContextMiddleware
from multimodal_rag.adapters.http.routes_questions import questions_router
from multimodal_rag.answering.domain import Answer, NotEnoughReason
from multimodal_rag.answering.errors import SearchUnavailableError

BODY = json.dumps({"question": "What is a shunt generator?"}).encode()


class RecordingUseCase:
    """Stands in for AnswerQuestion: answers or fails at once, or waits until
    cancelled."""

    def __init__(self, *, hang: bool, error: Exception | None = None) -> None:
        self.hang = hang
        self.error = error
        self.started = asyncio.Event()
        self.cancelled = False

    async def __call__(self, text: str, **_: Any) -> Answer:
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return Answer.not_enough(NotEnoughReason.NO_RELEVANT_CONTENT, "Not enough.")


async def call(use_case: RecordingUseCase, *, disconnect: bool) -> list[Message]:
    app = create_app(readiness_checks={}, routers=(questions_router,))
    app.dependency_overrides[provide_answer_question] = lambda: use_case
    sent: list[Message] = []
    body_sent = False

    async def receive() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": BODY, "more_body": False}
        if disconnect:
            await use_case.started.wait()
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/questions",
        "raw_path": b"/api/v1/questions",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(BODY)).encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
    }
    async with asyncio.timeout(2):
        await RequestContextMiddleware(app)(scope, receive, send)
    return sent


async def test_a_client_disconnect_cancels_the_running_question() -> None:
    use_case = RecordingUseCase(hang=True)

    sent = await call(use_case, disconnect=True)

    assert use_case.cancelled
    [start] = [m for m in sent if m["type"] == "http.response.start"]
    assert start["status"] == 499


async def test_a_connected_client_receives_the_answer() -> None:
    use_case = RecordingUseCase(hang=False)

    sent = await call(use_case, disconnect=False)

    [start] = [m for m in sent if m["type"] == "http.response.start"]
    assert start["status"] == 200
    assert not use_case.cancelled
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    assert json.loads(body)["reason"] == "no_relevant_content"


async def test_a_failure_of_the_question_keeps_its_own_status() -> None:
    use_case = RecordingUseCase(hang=False, error=SearchUnavailableError())

    sent = await call(use_case, disconnect=False)

    [start] = [m for m in sent if m["type"] == "http.response.start"]
    assert start["status"] == 503
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    assert json.loads(body)["code"] == "search_unavailable"
