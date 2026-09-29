import json
from pathlib import Path

import pytest

from tests.evaluation.evaluate_relevance import (
    DEFAULT_SET,
    LabeledQuestion,
    Outcome,
    evaluate,
    load_questions,
    supplies_expected_page,
    top_relevances_from_log,
)

QUOTE = "labeled_total.pdf"


def outcome(
    question: LabeledQuestion,
    *,
    reason: str | None = None,
    seconds: float = 0.2,
    sources: tuple[dict[str, object], ...] = (),
) -> Outcome:
    status = "answered" if reason is None else "not_enough_information"
    return Outcome(
        question=question,
        status=status,
        reason=reason,
        seconds=seconds,
        sources=sources,
        request_id="",
    )


def answerable(
    text: str,
    *,
    expected_document: str | None = None,
    expected_pages: tuple[int, ...] = (),
    identifier: str | None = None,
) -> LabeledQuestion:
    return LabeledQuestion(
        id=text,
        question=text,
        label="answerable",
        expected_document=expected_document,
        expected_pages=expected_pages,
        identifier=identifier,
    )


def negative(text: str) -> LabeledQuestion:
    return LabeledQuestion(id=text, question=text, label="hard_negative")


def by_name(outcomes: list[Outcome]) -> dict[str, tuple[int, int, bool]]:
    return {c.name: (c.passed, c.total, c.met) for c in evaluate(outcomes)}


def test_short_questions_count_words_without_punctuation() -> None:
    assert answerable("¿Total Neto?").short
    assert answerable("visión de la empresa").short is False
    assert answerable("magneto timing check").short


def test_a_question_stopped_by_the_gate_did_not_reach_the_model() -> None:
    stopped = outcome(negative("x"), reason="no_relevant_content")
    abstained = outcome(negative("y"), reason="not_answered_by_sources")
    cut = outcome(negative("z"), reason="answer_model_invalid_response")
    unjudged = outcome(negative("w"), reason="reranker_unavailable")

    assert not stopped.reached_model
    assert abstained.reached_model
    assert cut.reached_model
    assert not unjudged.reached_model


def test_the_criteria_count_their_own_questions() -> None:
    outcomes = [
        outcome(answerable("Total Neto")),
        outcome(answerable("Why is a series generator never used?")),
        outcome(answerable("PSRAM"), reason="no_relevant_content"),
        outcome(negative("Who wrote it?"), reason="no_relevant_content", seconds=0.4),
        outcome(negative("What does it cost?"), reason="not_answered_by_sources"),
    ]

    criteria = by_name(outcomes)

    assert criteria["SC-001 answerable reach the model"] == (2, 3, False)
    assert criteria["SC-002 short answerable reach the model"] == (1, 2, False)
    assert criteria["SC-003 unanswerable stopped by the gate"] == (1, 2, False)
    assert criteria["SC-003 unanswerable end as not enough information"] == (
        2,
        2,
        True,
    )


def test_the_judging_time_is_the_p95_of_questions_stopped_by_the_gate() -> None:
    outcomes = [
        outcome(negative(f"q{n}"), reason="no_relevant_content", seconds=n / 5)
        for n in range(1, 21)
    ] + [outcome(answerable("slow answer"), seconds=12.0)]

    [time] = [c for c in evaluate(outcomes) if c.name.startswith("SC-004")]

    assert time.value == pytest.approx(3.81)
    assert time.met is False


@pytest.mark.parametrize(
    ("sources", "supplied"),
    [
        (({"document_name": QUOTE, "pages": [1, 2], "relevance": 0.9},), True),
        (({"document_name": QUOTE, "pages": [1], "relevance": 0.9},), False),
        (({"document_name": "other.pdf", "pages": [2], "relevance": 0.9},), False),
        ((), False),
    ],
)
def test_an_identifier_counts_only_with_its_document_and_page(
    sources: tuple[dict[str, object], ...], supplied: bool
) -> None:
    question = answerable(
        "PE-204", expected_document=QUOTE, expected_pages=(2,), identifier="PE-204"
    )

    assert supplies_expected_page(outcome(question, sources=sources)) is supplied


def test_top_relevances_are_read_by_request_id_from_the_json_log() -> None:
    lines = [
        json.dumps({"request_id": "a", "message": "request completed"}),
        json.dumps(
            {
                "request_id": "b",
                "message": "question answered: outcome answered, "
                "top_relevance 0.970, search_ms 5.0",
            }
        ),
        "not json",
        json.dumps(["not", "a", "record"]),
    ]

    assert top_relevances_from_log(lines) == {"b": 0.970}


def test_the_labeled_set_has_what_the_success_criteria_need() -> None:
    questions = load_questions(DEFAULT_SET)

    assert len({question.id for question in questions}) == len(questions)
    answerable_ones = [q for q in questions if q.answerable]
    assert sum(q.short for q in answerable_ones) >= 10
    assert sum(q.label == "hard_negative" for q in questions) >= 10
    assert all(q.expected_document and q.expected_pages for q in answerable_ones)
    assert sum(q.identifier is not None for q in answerable_ones) >= 1


def test_questions_load_with_their_expectations(tmp_path: Path) -> None:
    path = tmp_path / "set.yaml"
    path.write_text(
        "questions:\n"
        "  - id: quote-total\n"
        '    question: "Total Neto"\n'
        "    language: es\n"
        "    label: answerable\n"
        f"    expected_document: {QUOTE}\n"
        "    expected_pages: [2]\n",
        encoding="utf-8",
    )

    [question] = load_questions(path)

    assert question == LabeledQuestion(
        id="quote-total",
        question="Total Neto",
        label="answerable",
        expected_document=QUOTE,
        expected_pages=(2,),
    )
