"""Plain-text rules shared by ingestion and answering.

Units are split into sentences at ingestion and answers are split into statements when
they are attributed, with the same sentence rule. Words are compared without accents
and case, as the keyword side of the index compares them.
"""

import re
import unicodedata

# A sentence ends at a period, question mark or exclamation mark followed by
# whitespace.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences at a terminator followed by whitespace.

    Args:
        text: Paragraph to split.

    Returns:
        The sentences in order, without surrounding whitespace.
    """
    return [sentence for sentence in SENTENCE_END.split(text.strip()) if sentence]


def fold(text: str) -> str:
    """Return a text in lowercase and without accents, for comparing words.

    Args:
        text: Text in any language.

    Returns:
        The case-folded text with every combining accent removed.
    """
    # Split accented letters into a base letter plus combining marks
    decomposed = unicodedata.normalize("NFKD", text.casefold())

    # Drop the combining marks, keeping the base letters
    return "".join(char for char in decomposed if not unicodedata.combining(char))
