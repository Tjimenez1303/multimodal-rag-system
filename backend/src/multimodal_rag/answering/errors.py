"""Errors specific to question answering, one per root cause.

Server errors carry a fixed message that names the failing component and never any
provider data, so the HTTP adapter can send it to clients as the problem detail.
"""

import uuid
from collections.abc import Sequence

from multimodal_rag.shared.errors import (
    CapacityError,
    ConcurrencyError,
    DataInconsistencyError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ValidationError,
)


class InvalidQuestionError(ValidationError):
    """The question is empty, too long, or restricted to an invalid document list."""

    code = "invalid_question"


class UnknownDocumentsError(ValidationError):
    """The question is restricted to documents that do not exist.

    Args:
        document_ids: The ids that match no document.
    """

    code = "unknown_documents"

    def __init__(self, document_ids: Sequence[uuid.UUID]) -> None:
        self.document_ids = tuple(document_ids)
        super().__init__(f"Unknown documents: {_joined(self.document_ids)}")


class DocumentsNotReadyError(ConcurrencyError):
    """The question is restricted to documents whose ingestion has not completed.

    Args:
        document_ids: The ids whose latest ingestion job is not completed.
    """

    code = "documents_not_ready"

    def __init__(self, document_ids: Sequence[uuid.UUID]) -> None:
        self.document_ids = tuple(document_ids)
        super().__init__(
            f"Documents not ready for questions: {_joined(self.document_ids)}"
        )


class AnsweringBusyError(CapacityError):
    """Every answering place and every waiting place is taken."""

    code = "answering_busy"

    def __init__(self) -> None:
        super().__init__("Too many questions are being answered. Retry later.")


class SearchUnavailableError(ProviderUnavailableError):
    """The embedding model or the vector index stayed unreachable after retries."""

    code = "search_unavailable"

    def __init__(self) -> None:
        super().__init__("Search is unavailable.")


class SearchTimeoutError(ProviderTimeoutError):
    """The embedding model or the vector index kept timing out after retries."""

    code = "search_timeout"

    def __init__(self) -> None:
        super().__init__("Search did not answer in time.")


class AnswerModelUnavailableError(ProviderUnavailableError):
    """The answer model stayed unreachable after retries."""

    code = "answer_model_unavailable"

    def __init__(self) -> None:
        super().__init__("The answer model is unavailable.")


class AnswerModelTimeoutError(ProviderTimeoutError):
    """The answer model kept timing out after retries."""

    code = "answer_model_timeout"

    def __init__(self) -> None:
        super().__init__("The answer model did not answer in time.")


class AnswerModelResponseError(ProviderResponseError):
    """The answer model rejected the request or returned an unusable answer."""

    code = "answer_model_invalid_response"

    def __init__(self) -> None:
        super().__init__("The answer model returned an answer that cannot be used.")


class RerankerUnavailableError(ProviderUnavailableError):
    """The reranker stayed unreachable after retries."""

    code = "reranker_unavailable"

    def __init__(self) -> None:
        super().__init__("The reranker is unavailable.")


class RerankerTimeoutError(ProviderTimeoutError):
    """The reranker kept timing out after retries."""

    code = "reranker_timeout"

    def __init__(self) -> None:
        super().__init__("The reranker did not answer in time.")


class RerankerResponseError(ProviderResponseError):
    """The reranker rejected the request or returned an unusable judgement."""

    code = "reranker_invalid_response"

    def __init__(self) -> None:
        super().__init__("The reranker returned a judgement that cannot be used.")


class InvalidRelevanceError(DataInconsistencyError):
    """A judged relevance lies outside 0 to 1."""

    code = "invalid_relevance"


class AnswerDeadlineExceededError(ProviderTimeoutError):
    """The question was not answered within the total deadline, waiting included."""

    code = "answer_deadline_exceeded"

    def __init__(self) -> None:
        super().__init__("The question was not answered within the deadline.")


def _joined(document_ids: Sequence[uuid.UUID]) -> str:
    return ", ".join(str(document_id) for document_id in document_ids)
