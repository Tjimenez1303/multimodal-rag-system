"""Route that answers questions from the ingested documents."""

from typing import Any

from fastapi import APIRouter, Request

from multimodal_rag.adapters.http.dependencies import AnswerQuestionDep
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

questions_router = APIRouter(prefix=API_PREFIX, tags=["questions"])


@questions_router.post(
    "/questions",
    operation_id="askQuestion",
    description=(
        "Searches the completed documents by meaning and by exact keywords, asks the "
        "local answer model when relevant content exists, and returns the answer with "
        "numbered citations. When the documents do not support an answer, status is "
        "not_enough_information and no citation or image is returned."
    ),
    openapi_extra={"parameters": [REQUEST_ID_PARAMETER]},
    responses=_PROBLEMS,
)
async def ask_question(
    body: QuestionBody, answer: AnswerQuestionDep, request: Request
) -> AnswerBody:
    """Answer a question only from the retrieved content of the documents.

    Args:
        body: The question.
        answer: Question use case.
        request: Request being handled, used to build image URLs.

    Returns:
        The answer, its citations, the sources supplied to the answer model and the
        figures that go with it.
    """

    def image_url(image: AnswerImage) -> str:
        return request.url_for(
            "get_document_image",
            document_id=str(image.document_id),
            element_id=str(image.element_id),
        ).path

    return AnswerBody.from_answer(await answer(body.question), image_url=image_url)
