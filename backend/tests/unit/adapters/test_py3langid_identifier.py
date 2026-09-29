import pytest

from multimodal_rag.adapters.language.py3langid_identifier import Py3LangidIdentifier

CANDIDATES = ("en", "es")


@pytest.fixture(scope="module")
def identifier() -> Py3LangidIdentifier:
    return Py3LangidIdentifier()


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("Why is a series wound generator never used on airplanes?", "en"),
        ("What is the best recipe for Spanish paella?", "en"),
        ("What is the torque for the cylinder head bolts of a Boeing 737 APU?", "en"),
        ("How is a shunt generator wired?", "en"),
        ("¿Por qué no se usa un generador en series en los aviones?", "es"),
        (
            "¿Por qué no se usa un generador en series en los aviones y cuánto pesa "
            "uno?",
            "es",
        ),
        ("¿Qué es un generador en derivación?", "es"),
    ],
)
def test_short_questions_are_identified_among_the_candidates(
    identifier: Py3LangidIdentifier, question: str, language: str
) -> None:
    assert identifier.identify(question, candidates=CANDIDATES) == language


@pytest.mark.parametrize("text", ["SPL-480", "737", "?", "Bonjour, où est la gare?"])
def test_the_result_is_always_one_of_the_candidates(
    identifier: Py3LangidIdentifier, text: str
) -> None:
    assert identifier.identify(text, candidates=CANDIDATES) in CANDIDATES


def test_a_single_candidate_is_always_chosen(identifier: Py3LangidIdentifier) -> None:
    question = "Why is a series wound generator never used?"

    assert identifier.identify(question, candidates=("es",)) == "es"


def test_a_candidate_the_model_does_not_know_falls_back_to_the_first(
    identifier: Py3LangidIdentifier,
) -> None:
    assert identifier.identify("Hello", candidates=("xx",)) == "xx"
