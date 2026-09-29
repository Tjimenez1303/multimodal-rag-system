"""``TokenCounter`` backed by the Hugging Face tokenizer of the embedding model.

The image bakes the model's ``tokenizer.json`` at a pinned revision. Counts include the
special tokens the tokenizer appends, which is what the served model reads: for
Qwen3-Embedding the end-of-text token that its last-token pooling relies on.
"""

from pathlib import Path
from typing import Self

from tokenizers import Tokenizer

from multimodal_rag.shared.errors import ConfigurationError


class HuggingFaceTokenCounter:
    """Counts and truncates text with the embedding model's tokenizer.

    Args:
        tokenizer: Loaded tokenizer of the embedding model.
    """

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer
        self._special_tokens = len(tokenizer.encode("").ids)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        """Load a tokenizer saved as ``tokenizer.json``.

        Args:
            path: File written by ``hf download`` at image build time.

        Returns:
            The token counter.

        Raises:
            ConfigurationError: If the file does not exist.
        """
        if not path.is_file():
            raise ConfigurationError(f"The embedding tokenizer file {path} is missing")
        return cls(Tokenizer.from_file(str(path)))

    def count(self, text: str) -> int:
        """Return the number of tokens the embedding model reads for a text.

        Args:
            text: Text to count.

        Returns:
            The token count, special tokens included.
        """
        return len(self._tokenizer.encode(text).ids)

    def truncate(self, text: str, max_tokens: int) -> str:
        """Cut a text at a token boundary so the model reads at most ``max_tokens``.

        Args:
            text: Text to shorten.
            max_tokens: Largest token count, special tokens included.

        Returns:
            The text itself when it fits, or its longest prefix that fits.
        """
        if self.count(text) <= max_tokens:
            return text
        budget = max_tokens - self._special_tokens
        if budget <= 0:
            return ""
        # Offsets map each token back to its characters in the original text.
        offsets = self._tokenizer.encode(text, add_special_tokens=False).offsets
        return text[: offsets[budget - 1][1]]
