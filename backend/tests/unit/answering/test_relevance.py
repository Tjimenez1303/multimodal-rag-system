import pytest

from multimodal_rag.answering.relevance import distinct_hits, passes_gate
from multimodal_rag.ingestion.ports import SearchHit
from tests.library import document, element, hit, unit

MANUAL = document("faa-powerplant.pdf")


def hits_with(*similarities: float) -> list[SearchHit]:
    paragraph = element(MANUAL)
    return [
        hit(unit(MANUAL, "Generators.", members=[paragraph]), similarity=similarity)
        for similarity in similarities
    ]


@pytest.mark.parametrize(
    ("similarity", "passes"), [(0.60, True), (0.5999, False), (0.82, True)]
)
def test_a_hit_passes_from_the_minimum_similarity(
    similarity: float, passes: bool
) -> None:
    assert passes_gate(hits_with(similarity), min_similarity=0.60) is passes


def test_the_gate_passes_when_any_hit_passes() -> None:
    assert passes_gate(hits_with(0.30, 0.41, 0.61, 0.12), min_similarity=0.60)
    assert not passes_gate(hits_with(0.30, 0.41, 0.59), min_similarity=0.60)


def test_no_hits_never_pass() -> None:
    assert not passes_gate([], min_similarity=0.0)


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
