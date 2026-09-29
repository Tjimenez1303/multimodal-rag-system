import uuid

import pytest

from multimodal_rag.answering.domain import (
    Answer,
    AnswerStatus,
    NotEnoughReason,
    Question,
)
from multimodal_rag.answering.errors import (
    DocumentsNotReadyError,
    InvalidQuestionError,
    UnknownDocumentsError,
)


def create(text: str, document_ids: list[uuid.UUID] | None = None) -> Question:
    return Question.create(
        text, document_ids=document_ids, max_chars=20, max_documents=2
    )


class TestQuestion:
    def test_the_text_is_trimmed(self) -> None:
        question = create("  What is SPL-480?\n")

        assert question == Question(text="What is SPL-480?", document_ids=None)

    @pytest.mark.parametrize("text", ["", "   \n\t"])
    def test_an_empty_question_is_rejected(self, text: str) -> None:
        with pytest.raises(InvalidQuestionError, match="empty"):
            create(text)

    def test_the_limit_counts_the_trimmed_text(self) -> None:
        assert create(f"  {'a' * 20}  ").text == "a" * 20

        with pytest.raises(InvalidQuestionError, match="21 characters"):
            create("a" * 21)

    def test_a_restriction_keeps_its_ids_in_order(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()

        question = create("x", [second, first])

        assert question.document_ids == (second, first)

    @pytest.mark.parametrize("count", [0, 3])
    def test_a_restriction_holds_one_to_the_maximum_ids(self, count: int) -> None:
        ids = [uuid.uuid4() for _ in range(count)]

        with pytest.raises(InvalidQuestionError, match="1 to 2"):
            create("x", ids)

    def test_a_restriction_cannot_repeat_an_id(self) -> None:
        repeated = uuid.uuid4()

        with pytest.raises(InvalidQuestionError, match="repeat"):
            create("x", [repeated, repeated])


def test_a_not_enough_answer_has_no_citations_sources_or_images() -> None:
    answer = Answer.not_enough(NotEnoughReason.NO_RELEVANT_CONTENT, "Not enough.")

    assert answer.status is AnswerStatus.NOT_ENOUGH_INFORMATION
    assert answer.reason is NotEnoughReason.NO_RELEVANT_CONTENT
    assert (answer.text, answer.not_covered) == ("Not enough.", None)
    assert answer.citations == ()
    assert answer.sources == ()
    assert answer.related_images == ()
    assert answer.primary_image is None


@pytest.mark.parametrize("error", [UnknownDocumentsError, DocumentsNotReadyError])
def test_restriction_errors_name_the_offending_documents(
    error: type[UnknownDocumentsError] | type[DocumentsNotReadyError],
) -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]

    raised = error(ids)

    assert raised.document_ids == tuple(ids)
    assert all(str(document_id) in str(raised) for document_id in ids)
