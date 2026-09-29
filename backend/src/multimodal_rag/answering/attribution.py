"""Citations for an answer the model wrote without any source marker.

The answer is split into statements, and each statement is matched against every
supplied unit with RAGFlow's weighting: mostly the share of the statement's words
found in the unit, and partly the cosine similarity of their embeddings. A statement
whose best match reaches the minimum score gets that unit's marker, so every citation
still points to a supplied unit. The caller computes the embeddings, because this
module does not reach the embedding model.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from multimodal_rag.ingestion.domain import RetrievalUnit
from multimodal_rag.shared.text import SENTENCE_END, fold

# RAGFlow's weights in InsertCitations: shared words count more than meaning.
WORD_WEIGHT = 0.7
VECTOR_WEIGHT = 0.3
# Shorter statements, such as "1." or "Desconectar.", are list numbers or labels.
MIN_STATEMENT_WORDS = 3
# Words of one or two letters, such as articles, carry no evidence.
MIN_WORD_LENGTH = 3
_WORD = re.compile(r"[\w-]+")
_LINE = re.compile(r"[^\n]+")
_FINAL_PUNCTUATION = ".!?:;"


@dataclass(frozen=True, slots=True)
class Attribution:
    """An answer with the markers attribution added.

    Attributes:
        text: The answer with a marker after every attributed statement.
        attributed: Statements that received a marker.
    """

    text: str
    attributed: int


@dataclass(frozen=True, slots=True)
class Statement:
    """A sentence or line of an answer that can carry a citation.

    Attributes:
        text: The statement as written, without surrounding spaces.
        end: Offset in the answer just after the statement.
    """

    text: str
    end: int


def find_statements(answer: str) -> tuple[Statement, ...]:
    """Split an answer into statements, lines first and then sentences.

    Args:
        answer: Answer text, possibly with Markdown lists.

    Returns:
        The statements of at least ``MIN_STATEMENT_WORDS`` words, in order.
    """
    statements = []
    for line in _LINE.finditer(answer):
        start = line.start()
        for separator in [*SENTENCE_END.finditer(line.group()), None]:
            stop = line.end() if separator is None else line.start() + separator.start()
            piece = answer[start:stop]
            text = piece.strip()
            if len(_WORD.findall(text)) >= MIN_STATEMENT_WORDS:
                end = start + len(piece.rstrip())
                statements.append(Statement(text=text, end=end))
            if separator is not None:
                start = line.start() + separator.end()
    return tuple(statements)


def attribute(
    answer: str,
    statements: Sequence[Statement],
    *,
    units: Sequence[RetrievalUnit],
    statement_vectors: Sequence[Sequence[float]],
    unit_vectors: Sequence[Sequence[float]],
    min_score: float,
) -> Attribution:
    """Add the marker of its best matching unit after each statement.

    Args:
        answer: Answer text without markers.
        statements: Statements found in the answer by ``find_statements``.
        units: Units supplied to the model, numbered from 1 in this order.
        statement_vectors: Embedding of each statement, in the same order.
        unit_vectors: Embedding of each unit's ``embedding_text``, in the same order.
        min_score: Lowest weighted score that attributes a statement.

    Returns:
        The answer with a ``[n]`` marker after every attributed statement, before its
        final punctuation, and the count of attributed statements.

    Raises:
        ValueError: If the vectors do not match the statements and units.
    """
    unit_words = [_words(unit.embedding_text) for unit in units]
    markers: list[tuple[int, int]] = []
    for statement, vector in zip(statements, statement_vectors, strict=True):
        words = _words(statement.text)
        scores = [
            WORD_WEIGHT * _share(words, candidate) + VECTOR_WEIGHT * _cosine(vector, v)
            for candidate, v in zip(unit_words, unit_vectors, strict=True)
        ]
        best = max(range(len(scores)), key=scores.__getitem__, default=None)
        if best is not None and scores[best] >= min_score:
            markers.append((statement.end, best + 1))
    for end, number in reversed(markers):
        answer = _with_marker(answer, end=end, number=number)
    return Attribution(text=answer, attributed=len(markers))


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(fold(text)) if len(word) >= MIN_WORD_LENGTH}


def _share(words: set[str], candidate: set[str]) -> float:
    return len(words & candidate) / len(words) if words else 0.0


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    norms = math.hypot(*first) * math.hypot(*second)
    return math.sumprod(first, second) / norms if norms else 0.0


def _with_marker(answer: str, *, end: int, number: int) -> str:
    at = end - 1 if answer[end - 1] in _FINAL_PUNCTUATION else end
    return f"{answer[:at]} [{number}]{answer[at:]}"
