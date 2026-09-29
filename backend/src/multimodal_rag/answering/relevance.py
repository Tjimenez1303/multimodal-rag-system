"""The relevance gate that decides whether the answer model is asked at all.

The fused rank score of a hybrid search cannot tell a relevant unit from the best of
irrelevant ones, so the gate reads the dense cosine similarity of each hit, which is
comparable across questions. When no hit reaches the minimum, the documents do not
contain the answer and no model call is spent on the question.

Identifiers such as part numbers and error codes carry little meaning for the embedding
model, so a question about ``SPL-480`` scores low even when the keyword side of the
search found the unit that holds it. A hit that contains, as a whole token, an
identifier from the question therefore passes the gate too. Units whose text repeats a
better ranked unit, such as the same manual uploaded twice, are dropped so that they do
not take the model's slots.
"""

import re
from collections.abc import Sequence

from multimodal_rag.ingestion.ports import SearchHit
from multimodal_rag.shared.text import fold

# Letters, digits, "-", "." and "/" between a letter or digit at each end, so the
# punctuation that ends a sentence is left out.
_TOKEN = re.compile(r"[^\W_](?:[\w./-]*[^\W_])?")
_DIGIT = re.compile(r"\d")
MIN_IDENTIFIER_CHARS = 3


def question_identifiers(question: str) -> set[str]:
    """Return the identifiers a question mentions, such as ``SPL-480`` or ``2-71``.

    Args:
        question: The question text.

    Returns:
        The tokens of at least ``MIN_IDENTIFIER_CHARS`` characters that contain a
        digit, in lowercase and without accents.
    """
    return {
        token
        for token in _TOKEN.findall(fold(question))
        if len(token) >= MIN_IDENTIFIER_CHARS and _DIGIT.search(token)
    }


def passes_gate(
    hits: Sequence[SearchHit], *, min_similarity: float, question: str
) -> bool:
    """Return whether the retrieved units are relevant enough to ask the model.

    Args:
        hits: Units retrieved for the question.
        min_similarity: Lowest dense similarity of a relevant unit.
        question: The question text, whose identifiers let a unit pass.

    Returns:
        ``True`` when at least one hit reaches ``min_similarity`` or holds an
        identifier of the question as a whole token.
    """
    if any(hit.similarity >= min_similarity for hit in hits):
        return True
    identifiers = question_identifiers(question)
    return bool(identifiers) and any(
        identifiers & set(_TOKEN.findall(fold(hit.unit.embedding_text))) for hit in hits
    )


def distinct_hits(hits: Sequence[SearchHit], *, limit: int) -> list[SearchHit]:
    """Keep the best ranked hit of every distinct unit text, up to a limit.

    Args:
        hits: Hits in rank order.
        limit: Largest number of hits to keep.

    Returns:
        The hits whose text, ignoring case, accents and spacing, differs from every
        better ranked hit, in rank order.
    """
    seen: set[str] = set()
    kept: list[SearchHit] = []
    for hit in hits:
        key = " ".join(fold(hit.unit.text).split())
        if key not in seen and len(kept) < limit:
            seen.add(key)
            kept.append(hit)
    return kept
