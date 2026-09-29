"""``LanguageIdentifier`` over py3langid, a Naive Bayes classifier of 97 languages.

The model is loaded once. Its raw score of a language does not depend on the other
languages, so keeping the best ranked candidate gives the same answer as restricting the
model to the candidates, without changing the shared model on each call.
"""

from collections.abc import Sequence

from py3langid.langid import MODEL_FILE, LanguageIdentifier


class Py3LangidIdentifier:
    """Identifies the language of short texts such as questions."""

    def __init__(self) -> None:
        self._model = LanguageIdentifier.from_model_file(MODEL_FILE)

    def identify(self, text: str, *, candidates: Sequence[str]) -> str:
        """Return the most likely language of a text among some candidates.

        Args:
            text: Text to classify.
            candidates: ISO 639-1 codes the answer is chosen from.

        Returns:
            The best ranked candidate, or the first candidate when the model knows
            none of them.
        """
        ranking: list[tuple[str, float]] = self._model.rank(text)
        allowed = set(candidates)
        return next(
            (language for language, _ in ranking if language in allowed), candidates[0]
        )
