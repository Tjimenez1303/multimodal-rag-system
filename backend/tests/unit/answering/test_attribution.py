import pytest

from multimodal_rag.answering.attribution import attribute, find_statements
from multimodal_rag.ingestion.domain import RetrievalUnit
from tests.library import document, element, unit

MANUAL = document("faa-powerplant.pdf")
NEAR = [1.0, 0.0]
FAR = [0.0, 1.0]


def source(text: str) -> RetrievalUnit:
    return unit(MANUAL, text, members=[element(MANUAL)], heading_path=())


def test_statements_are_split_by_line_and_then_by_sentence() -> None:
    answer = "The field is in series. It regulates poorly!\n- A shunt field is parallel"

    statements = find_statements(answer)

    assert [s.text for s in statements] == [
        "The field is in series.",
        "It regulates poorly!",
        "- A shunt field is parallel",
    ]


def test_statements_under_three_words_are_left_out() -> None:
    answer = "Las reglas son:\n1. Desconectar.\n2. Verificar la ausencia de tensión."

    statements = find_statements(answer)

    assert [s.text for s in statements] == [
        "Las reglas son:",
        "Verificar la ausencia de tensión.",
    ]


def test_the_marker_goes_before_the_final_punctuation() -> None:
    answer = "Series generators regulate poorly.\n- Shunt generators regulate well"
    units = [source("Series generators regulate poorly under load.")]
    units.append(source("Shunt generators regulate well."))
    statements = find_statements(answer)

    attributed = attribute(
        answer,
        statements,
        units=units,
        statement_vectors=[NEAR, FAR],
        unit_vectors=[NEAR, FAR],
        min_score=0.5,
    )

    assert attributed.text == (
        "Series generators regulate poorly [1].\n- Shunt generators regulate well [2]"
    )
    assert attributed.attributed == 2


def test_shared_words_outweigh_meaning_as_in_ragflow() -> None:
    answer = "The rheostat controls the field current."
    # Unit 1 is closest in meaning, unit 2 holds the statement's words.
    units = [
        source("Voltage adjustment."),
        source("A rheostat controls field current."),
    ]

    attributed = attribute(
        answer,
        find_statements(answer),
        units=units,
        statement_vectors=[NEAR],
        unit_vectors=[NEAR, FAR],
        min_score=0.5,
    )

    assert attributed.text == "The rheostat controls the field current [2]."


def test_a_statement_below_the_minimum_score_gets_no_marker() -> None:
    answer = "Magnetos fire the spark plugs in order."
    units = [source("Generators charge the battery.")]

    attributed = attribute(
        answer,
        find_statements(answer),
        units=units,
        statement_vectors=[NEAR],
        unit_vectors=[FAR],
        min_score=0.5,
    )

    assert (attributed.text, attributed.attributed) == (answer, 0)


def test_word_matching_ignores_accents_and_case() -> None:
    answer = "Verificar la AUSENCIA de tension."
    units = [source("Verificar la ausencia de tensión en la instalación.")]

    attributed = attribute(
        answer,
        find_statements(answer),
        units=units,
        statement_vectors=[FAR],
        unit_vectors=[NEAR],
        min_score=0.5,
    )

    assert attributed.text == "Verificar la AUSENCIA de tension [1]."


def test_vectors_must_match_the_statements_and_units() -> None:
    answer = "Magnetos fire the spark plugs in order."

    with pytest.raises(ValueError, match="zip"):
        attribute(
            answer,
            find_statements(answer),
            units=[source("x y z")],
            statement_vectors=[],
            unit_vectors=[NEAR],
            min_score=0.5,
        )
