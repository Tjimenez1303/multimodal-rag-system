import pytest

from multimodal_rag.answering.domain import JudgedHit
from multimodal_rag.answering.relevance import (
    distinct_hits,
    passes_gate,
    question_identifiers,
    rank_by_relevance,
)
from multimodal_rag.ingestion.ports import SearchHit
from tests.library import document, element, hit, unit

MANUAL = document("faa-powerplant.pdf")


QUESTION = "Why is a series wound generator never used?"


def judged(
    *relevances: float, similarity: float = 0.8, text: str = "Generators."
) -> list[JudgedHit]:
    paragraph = element(MANUAL)
    return [
        JudgedHit(
            hit=hit(unit(MANUAL, text, members=[paragraph]), similarity=similarity),
            relevance=relevance,
        )
        for relevance in relevances
    ]


@pytest.mark.parametrize(
    ("relevance", "passes"), [(0.30, True), (0.2999, False), (0.97, True)]
)
def test_a_hit_passes_from_the_minimum_relevance(
    relevance: float, passes: bool
) -> None:
    gate = passes_gate(judged(relevance), min_relevance=0.30, question=QUESTION)

    assert gate is passes


def test_the_gate_passes_when_any_hit_passes() -> None:
    passing = judged(0.02, 0.11, 0.31, 0.05)
    failing = judged(0.02, 0.11, 0.29)

    assert passes_gate(passing, min_relevance=0.30, question=QUESTION)
    assert not passes_gate(failing, min_relevance=0.30, question=QUESTION)


def test_a_high_similarity_does_not_open_the_gate() -> None:
    hits = judged(0.10, similarity=0.95)

    assert not passes_gate(hits, min_relevance=0.30, question=QUESTION)


def test_a_low_similarity_does_not_close_the_gate() -> None:
    hits = judged(0.90, similarity=0.20)

    assert passes_gate(hits, min_relevance=0.30, question=QUESTION)


def test_no_hits_never_pass() -> None:
    assert not passes_gate([], min_relevance=0.0, question=QUESTION)


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
        hits = judged(0.05, text="Code spl-480: low oil pressure.")

        assert passes_gate(hits, min_relevance=0.30, question="What is SPL-480?")

    def test_an_identifier_matches_only_as_a_whole_token(self) -> None:
        hits = judged(0.05, text="Codes SPL-4801 and XSPL-480 are listed.")

        assert not passes_gate(hits, min_relevance=0.30, question="What is SPL-480?")

    def test_an_identifier_absent_from_every_hit_does_not_pass(self) -> None:
        hits = judged(0.05, 0.12, text="Code SPL-490: high oil temperature.")

        assert not passes_gate(hits, min_relevance=0.30, question="What is SPL-480?")

    def test_an_identifier_matches_with_accents_and_case_folded(self) -> None:
        hits = judged(0.05, text="Válvula ÑA-480 abierta.")

        assert passes_gate(hits, min_relevance=0.30, question="¿Qué es na-480?")


class TestRankByRelevance:
    @staticmethod
    def candidates(*texts: str) -> list[SearchHit]:
        return [hit(unit(MANUAL, text, members=[element(MANUAL)])) for text in texts]

    def test_candidates_are_ordered_by_descending_relevance(self) -> None:
        hits = self.candidates("a", "b", "c")

        ranked = rank_by_relevance(hits, [0.2, 0.9, 0.5], limit=3, question=QUESTION)

        assert [item.hit for item in ranked] == [hits[1], hits[2], hits[0]]
        assert [item.relevance for item in ranked] == [0.9, 0.5, 0.2]

    def test_the_search_order_breaks_a_tie(self) -> None:
        hits = self.candidates("a", "b", "c")

        ranked = rank_by_relevance(hits, [0.4, 0.7, 0.7], limit=3, question=QUESTION)

        assert [item.hit for item in ranked] == [hits[1], hits[2], hits[0]]

    def test_the_limit_applies_after_sorting(self) -> None:
        hits = self.candidates("a", "b", "c", "d")

        ranked = rank_by_relevance(
            hits, [0.1, 0.2, 0.9, 0.8], limit=2, question=QUESTION
        )

        assert [item.hit for item in ranked] == [hits[2], hits[3]]

    def test_an_identifier_unit_replaces_the_lowest_judged_one(self) -> None:
        hits = self.candidates("a", "b", "c", "Code SPL-480 means low oil.")

        ranked = rank_by_relevance(
            hits, [0.9, 0.8, 0.7, 0.05], limit=3, question="What is SPL-480?"
        )

        assert [item.hit for item in ranked] == [hits[0], hits[1], hits[3]]

    def test_more_identifier_units_than_places_keep_the_highest_judged(self) -> None:
        hits = self.candidates("SPL-480 a", "SPL-480 b", "SPL-480 c", "other")

        ranked = rank_by_relevance(
            hits, [0.1, 0.3, 0.2, 0.9], limit=2, question="What is SPL-480?"
        )

        assert [item.hit for item in ranked] == [hits[1], hits[2]]
