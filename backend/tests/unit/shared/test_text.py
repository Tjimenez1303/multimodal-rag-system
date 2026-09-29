import pytest

from multimodal_rag.shared.text import fold, split_sentences


@pytest.mark.parametrize(
    ("text", "sentences"),
    [
        ("One. Two? Three!", ["One.", "Two?", "Three!"]),
        ("No terminator here", ["No terminator here"]),
        ("Version 2.5 is out. Next.", ["Version 2.5 is out.", "Next."]),
    ],
)
def test_sentences_end_at_a_terminator_followed_by_whitespace(
    text: str, sentences: list[str]
) -> None:
    assert split_sentences(text) == sentences


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Tensión ELÉCTRICA", "tension electrica"),
        ("Straße", "strasse"),
        ("V-12", "v-12"),
    ],
)
def test_folding_removes_case_and_accents(text: str, folded: str) -> None:
    assert fold(text) == folded
