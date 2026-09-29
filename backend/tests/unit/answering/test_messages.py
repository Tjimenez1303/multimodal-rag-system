import pytest

from multimodal_rag.answering.domain import NotEnoughReason
from multimodal_rag.answering.messages import SUPPORTED_LANGUAGES, not_enough_message


def test_english_and_spanish_are_the_supported_languages() -> None:
    assert SUPPORTED_LANGUAGES == ("en", "es")


@pytest.mark.parametrize("reason", list(NotEnoughReason))
def test_every_reason_has_a_distinct_english_and_spanish_message(
    reason: NotEnoughReason,
) -> None:
    english = not_enough_message(reason, language="en")
    spanish = not_enough_message(reason, language="es")

    assert english.strip()
    assert spanish.strip()
    assert english != spanish


@pytest.mark.parametrize("reason", list(NotEnoughReason))
def test_an_unknown_language_falls_back_to_english(reason: NotEnoughReason) -> None:
    assert not_enough_message(reason, language="fr") == not_enough_message(
        reason, language="en"
    )


def test_reasons_have_different_messages() -> None:
    messages = {not_enough_message(reason, language="en") for reason in NotEnoughReason}

    assert len(messages) == len(NotEnoughReason)
