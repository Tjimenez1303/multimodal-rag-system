"""The relevance gate that decides whether the answer model is asked at all.

The reranker judges each retrieved unit together with the question and gives the
probability that the unit contains the answer. The units with the highest judgement are
supplied to the answer model in that order, and the model is asked only when one of
them reaches the minimum relevance. When none does, the documents do not contain the
answer and no model call is spent on the question.

The dense cosine similarity of the hybrid search no longer gates. It is weakest for
short questions against long passages, and it cannot tell a passage about the right
subject that lacks the requested fact from one that states it. Reference systems gate
on a cross-encoder judgement instead, as the reranked relevance gate's research records.

Identifiers such as part numbers and error codes carry little meaning for a model, so a
question about ``SPL-480`` can be judged low even when the keyword side of the search
found the unit that holds it. A unit that contains, as a whole token, an identifier from
the question is therefore always supplied and lets the question through. Reference
systems keep such exact term evidence after reranking too: RAGFlow blends term
similarity with the reranker's score in ``rerank_by_model``. Units whose text repeats a
better ranked unit, such as the same manual uploaded twice, are dropped before judging,
so they neither take the model's places nor cost a judgement.
"""

import re
from collections.abc import Sequence

from multimodal_rag.answering.domain import JudgedHit
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


def rank_by_relevance(
    hits: Sequence[SearchHit],
    relevances: Sequence[float],
    *,
    limit: int,
    question: str,
) -> list[JudgedHit]:
    """Select the units supplied to the answer model, in judged order.

    Args:
        hits: Candidates in search order, which is the fused rank.
        relevances: The judgement of each candidate, in the same order.
        limit: Largest number of units to supply.
        question: The question text, whose identifiers keep their units.

    Returns:
        The ``limit`` candidates with the highest relevance, where each candidate
        holding an identifier of the question replaces the lowest judged candidate
        that holds none. Sorted by descending relevance, the search order breaking
        ties.
    """
    judged = [
        JudgedHit(hit=hit, relevance=relevance)
        for hit, relevance in zip(hits, relevances, strict=True)
    ]
    # Python's sort is stable, so equal judgements keep the search order.
    order = sorted(range(len(judged)), key=lambda index: -judged[index].relevance)
    identifiers = question_identifiers(question)
    pinned = [i for i in order if _holds_identifier(judged[i].hit, identifiers)]
    kept = set(pinned[:limit])
    kept.update([i for i in order if i not in kept][: limit - len(kept)])
    return [judged[i] for i in order if i in kept]


def passes_gate(
    judged: Sequence[JudgedHit], *, min_relevance: float, question: str
) -> bool:
    """Return whether the supplied units are relevant enough to ask the model.

    Args:
        judged: Units supplied to the answer model, with their judgement.
        min_relevance: Lowest judged relevance of a relevant unit.
        question: The question text, whose identifiers let a unit pass.

    Returns:
        ``True`` when at least one unit reaches ``min_relevance`` or holds an
        identifier of the question as a whole token.
    """
    if any(item.relevance >= min_relevance for item in judged):
        return True
    identifiers = question_identifiers(question)
    return any(_holds_identifier(item.hit, identifiers) for item in judged)


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


def _holds_identifier(hit: SearchHit, identifiers: set[str]) -> bool:
    return bool(identifiers & set(_TOKEN.findall(fold(hit.unit.embedding_text))))
