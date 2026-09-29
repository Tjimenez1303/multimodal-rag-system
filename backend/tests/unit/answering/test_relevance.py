import pytest

from multimodal_rag.answering.relevance import (
    distinct_hits,
    passes_gate,
    question_identifiers,
)
from multimodal_rag.ingestion.ports import SearchHit
from tests.library import document, element, hit, unit

MANUAL = document("faa-powerplant.pdf")


QUESTION = "Why is a series wound generator never used?"


def hits_with(*similarities: float, text: str = "Generators.") -> list[SearchHit]:
    paragraph = element(MANUAL)
    return [
        hit(unit(MANUAL, text, members=[paragraph]), similarity=similarity)
        for similarity in similarities
    ]


@pytest.mark.parametrize(
    ("similarity", "passes"), [(0.60, True), (0.5999, False), (0.82, True)]
)
def test_a_hit_passes_from_the_minimum_similarity(
    similarity: float, passes: bool
) -> None:
    gate = passes_gate(hits_with(similarity), min_similarity=0.60, question=QUESTION)

    assert gate is passes


def test_the_gate_passes_when_any_hit_passes() -> None:
    passing = hits_with(0.30, 0.41, 0.61, 0.12)
    failing = hits_with(0.30, 0.41, 0.59)

    assert passes_gate(passing, min_similarity=0.60, question=QUESTION)
    assert not passes_gate(failing, min_similarity=0.60, question=QUESTION)


def test_no_hits_never_pass() -> None:
    assert not passes_gate([], min_similarity=0.0, question=QUESTION)


def test_units_with_identical_text_keep_only_the_best_ranked() -> None:
    other = document("insst-copy.pdf")
    first = hit(
        unit(MANUAL, "Riesgo eléctrico.\nDefinición.", members=[element(MANUAL)])
    )
    copy = hit(
        unit(other, "  riesgo ELÉCTRICO. definición. ", members=[element(other)])
    )
    different = hit(unit(MANUAL, "Otra cosa.", members=[element(MANUAL)]))

    kept = distinct_hits([first, copy, different], limit=8)

    assert kept == [first, different]


def test_distinct_hits_stop_at_the_limit() -> None:
    hits = [
        hit(unit(MANUAL, f"Text {n}.", members=[element(MANUAL)])) for n in range(3)
    ]

    assert distinct_hits(hits, limit=2) == hits[:2]


class TestIdentifiers:
    @pytest.mark.parametrize(
        ("question", "identifiers"),
        [
            ("What is code SPL-480?", {"spl-480"}),
            ("Is the ODW-300 engine covered in TM 2-71?", {"odw-300", "2-71"}),
            ("Check valve V-12 and item 3.", {"v-12"}),
            ("Torque of part 1/4-20 and rev 2.5.1?", {"1/4-20", "2.5.1"}),
            ("Why is a series wound generator never used?", set()),
        ],
    )
    def test_identifiers_are_tokens_of_three_characters_with_a_digit(
        self, question: str, identifiers: set[str]
    ) -> None:
        assert question_identifiers(question) == identifiers

    def test_identifiers_ignore_case_and_accents(self) -> None:
        assert question_identifiers("¿Qué es el código ÑA-480?") == {"na-480"}

    def test_a_hit_below_the_minimum_passes_when_it_holds_a_question_identifier(
        self,
    ) -> None:
        hits = hits_with(0.42, text="Code spl-480: low oil pressure.")

        assert passes_gate(hits, min_similarity=0.60, question="What is SPL-480?")

    def test_an_identifier_matches_only_as_a_whole_token(self) -> None:
        hits = hits_with(0.42, text="Codes SPL-4801 and XSPL-480 are listed.")

        assert not passes_gate(hits, min_similarity=0.60, question="What is SPL-480?")

    def test_an_identifier_absent_from_every_hit_does_not_pass(self) -> None:
        hits = hits_with(0.42, 0.51, text="Code SPL-490: high oil temperature.")

        assert not passes_gate(hits, min_similarity=0.60, question="What is SPL-480?")

    def test_an_identifier_matches_with_accents_and_case_folded(self) -> None:
        hits = hits_with(0.30, text="Válvula ÑA-480 abierta.")

        assert passes_gate(hits, min_similarity=0.60, question="¿Qué es na-480?")
