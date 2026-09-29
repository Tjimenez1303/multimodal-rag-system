"""The relevance gate that decides whether the answer model is asked at all.

The fused rank score of a hybrid search cannot tell a relevant unit from the best of
irrelevant ones, so the gate reads the dense cosine similarity of each hit, which is
comparable across questions. When no hit reaches the minimum, the documents do not
contain the answer and no model call is spent on the question.
"""

from collections.abc import Sequence

from multimodal_rag.ingestion.ports import SearchHit


def passes_gate(hits: Sequence[SearchHit], *, min_similarity: float) -> bool:
    """Return whether the retrieved units are relevant enough to ask the model.

    Args:
        hits: Units retrieved for the question.
        min_similarity: Lowest dense similarity of a relevant unit.

    Returns:
        ``True`` when at least one hit reaches ``min_similarity``.
    """
    return any(hit.similarity >= min_similarity for hit in hits)
