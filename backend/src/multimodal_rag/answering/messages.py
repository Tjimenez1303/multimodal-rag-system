"""Fixed messages of the not-enough-information outcomes.

The answer model writes in the language of the question, but these outcomes can happen
without a model call, so the core carries its own messages in the languages it
supports, with English as the fallback.
"""

from multimodal_rag.answering.domain import NotEnoughReason

SUPPORTED_LANGUAGES = ("en", "es")
FALLBACK_LANGUAGE = "en"

_MESSAGES: dict[str, dict[NotEnoughReason, str]] = {
    "en": {
        NotEnoughReason.NO_SEARCHABLE_DOCUMENTS: (
            "There are no searchable documents yet. Upload a document and wait for "
            "its ingestion to complete."
        ),
        NotEnoughReason.NO_RELEVANT_CONTENT: (
            "The documents do not contain enough information to answer this question."
        ),
        NotEnoughReason.NOT_ANSWERED_BY_SOURCES: (
            "The passages found in the documents do not answer this question."
        ),
        NotEnoughReason.NO_VALID_CITATIONS: (
            "The answer could not be supported by citations to the documents, so it "
            "is not shown."
        ),
    },
    "es": {
        NotEnoughReason.NO_SEARCHABLE_DOCUMENTS: (
            "Todavía no hay documentos en los que buscar. Sube un documento y espera "
            "a que se complete su procesamiento."
        ),
        NotEnoughReason.NO_RELEVANT_CONTENT: (
            "Los documentos no contienen información suficiente para responder a "
            "esta pregunta."
        ),
        NotEnoughReason.NOT_ANSWERED_BY_SOURCES: (
            "Los fragmentos encontrados en los documentos no responden a esta pregunta."
        ),
        NotEnoughReason.NO_VALID_CITATIONS: (
            "La respuesta no se pudo respaldar con citas de los documentos, así que "
            "no se muestra."
        ),
    },
}


def not_enough_message(reason: NotEnoughReason, *, language: str) -> str:
    """Return the message of a not-enough-information outcome.

    Args:
        reason: Why the question has no answer.
        language: ISO 639-1 code of the question's language.

    Returns:
        The message in that language, or in English when it is not supported.
    """
    return _MESSAGES.get(language, _MESSAGES[FALLBACK_LANGUAGE])[reason]
