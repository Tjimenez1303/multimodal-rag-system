"""The relevance gate that decides whether the answer model is asked at all.

The fused rank score of a hybrid search cannot tell a relevant unit from the best of
irrelevant ones, so the gate reads the dense cosine similarity of each hit, which is
comparable across questions. When no hit reaches the minimum, the documents do not
contain the answer and no model call is spent on the question. Units whose text repeats
a better ranked unit, such as the same manual uploaded twice, are dropped so that they
do not take the model's slots.
"""

from collections.abc import Sequence

from multimodal_rag.ingestion.ports import SearchHit
from multimodal_rag.shared.text import fold


def passes_gate(hits: Sequence[SearchHit], *, min_similarity: float) -> bool:
    """Return whether the retrieved units are relevant enough to ask the model.

    Args:
        hits: Units retrieved for the question.
        min_similarity: Lowest dense similarity of a relevant unit.

    Returns:
        ``True`` when at least one hit reaches ``min_similarity``.
    """
    return any(hit.similarity >= min_similarity for hit in hits)


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
