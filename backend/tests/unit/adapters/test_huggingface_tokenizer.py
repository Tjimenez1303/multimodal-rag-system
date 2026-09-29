from pathlib import Path

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from tokenizers.processors import TemplateProcessing

from multimodal_rag.adapters.tokenizer.huggingface import HuggingFaceTokenCounter
from multimodal_rag.shared.errors import ConfigurationError

WORDS = ["one", "two", "three", "four", "five", "."]


@pytest.fixture
def tokenizer_file(tmp_path: Path) -> Path:
    """A word tokenizer that appends an end token, like Qwen3-Embedding."""
    vocab = {"[UNK]": 0, "<eos>": 1} | {word: n + 2 for n, word in enumerate(WORDS)}
    tokenizer = Tokenizer(WordLevel(vocab, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.post_processor = TemplateProcessing(
        single="$A <eos>", special_tokens=[("<eos>", 1)]
    )
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    return path


@pytest.fixture
def counter(tokenizer_file: Path) -> HuggingFaceTokenCounter:
    return HuggingFaceTokenCounter.from_file(tokenizer_file)


def test_counts_include_the_special_tokens_the_model_reads(
    counter: HuggingFaceTokenCounter,
) -> None:
    assert counter.count("one two three.") == 5


def test_text_that_fits_is_returned_unchanged(counter: HuggingFaceTokenCounter) -> None:
    assert counter.truncate("one two", 3) == "one two"


def test_text_is_cut_at_a_token_boundary_leaving_room_for_special_tokens(
    counter: HuggingFaceTokenCounter,
) -> None:
    truncated = counter.truncate("one two three four five", 4)

    assert truncated == "one two three"
    assert counter.count(truncated) == 4


def test_a_budget_without_room_for_text_returns_nothing(
    counter: HuggingFaceTokenCounter,
) -> None:
    assert counter.truncate("one two", 1) == ""


def test_a_missing_tokenizer_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="tokenizer"):
        HuggingFaceTokenCounter.from_file(tmp_path / "missing.json")
