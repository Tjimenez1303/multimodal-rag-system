"""Route that answers questions from the ingested documents."""

from typing import Any

from fastapi import APIRouter

from multimodal_rag.adapters.http.dependencies import AnswerQuestionDep
from multimodal_rag.adapters.http.problems import problem_responses
from multimodal_rag.adapters.http.routes_ingestion import (
    API_PREFIX,
    REQUEST_ID_PARAMETER,
)
from multimodal_rag.adapters.http.schemas import AnswerBody, QuestionBody

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
async def ask_question(body: QuestionBody, answer: AnswerQuestionDep) -> AnswerBody:
    """Answer a question only from the retrieved content of the documents.

    Args:
        body: The question.
        answer: Question use case.

    Returns:
        The answer, its citations and the sources supplied to the answer model.
    """
    return AnswerBody.from_answer(await answer(body.question))
