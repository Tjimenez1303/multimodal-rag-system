"""Route that answers questions from the ingested documents."""

from typing import Any

from fastapi import APIRouter, Request, Response

from multimodal_rag.adapters.http.dependencies import AnswerQuestionDep
from multimodal_rag.adapters.http.disconnect import run_until_disconnect
from multimodal_rag.adapters.http.problems import problem_responses
from multimodal_rag.adapters.http.routes_ingestion import (
    API_PREFIX,
    REQUEST_ID_PARAMETER,
)
from multimodal_rag.adapters.http.schemas import AnswerBody, QuestionBody
from multimodal_rag.answering.domain import AnswerImage

_RETRY_AFTER: dict[str, Any] = {
    "Retry-After": {
        "description": "Seconds to wait before retrying, sent with answering_busy",
        "schema": {"type": "integer", "minimum": 1},
    }
}
_PROBLEMS = problem_responses(400, 409, 502, 503, 504)
_PROBLEMS[503] = _PROBLEMS[503] | {"headers": _RETRY_AFTER}
# nginx's "Client Closed Request": nobody reads it, but the request log records it.
CLIENT_CLOSED_REQUEST = 499

questions_router = APIRouter(prefix=API_PREFIX, tags=["questions"])


@questions_router.post(
    "/questions",
    operation_id="askQuestion",
    description=(
        "Searches the completed documents by meaning and by exact keywords, asks the "
        "local answer model when relevant content exists, and returns the answer with "
        "numbered citations. When the documents do not support an answer, status is "
        "not_enough_information and no citation or image is returned. The request is "
        "cancelled when the client disconnects."
    ),
    openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    response_model=AnswerBody,
    responses=_PROBLEMS,
)
async def ask_question(
    body: QuestionBody, answer: AnswerQuestionDep, request: Request
) -> AnswerBody | Response:
    """Answer a question only from the retrieved content of the documents.

    Args:
        body: The question.
        answer: Question use case.
        request: Request being handled, used to build image URLs.

    Returns:
        The answer, its citations, the sources supplied to the answer model and the
        figures that go with it, or an empty 499 response when the client left.
    """

    def image_url(image: AnswerImage) -> str:
        return request.url_for(
            "get_document_image",
            document_id=str(image.document_id),
            element_id=str(image.element_id),
        ).path

    result = await run_until_disconnect(request, lambda: answer(body.question))
    if result is None:
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    return AnswerBody.from_answer(result, image_url=image_url)
