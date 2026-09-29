"""The tokenizer baked into the image counts tokens as the served model does."""

from pathlib import Path

import pytest

from multimodal_rag.adapters.tokenizer.huggingface import HuggingFaceTokenCounter


@pytest.fixture(scope="module")
def counter(embedder_tokenizer_path: Path) -> HuggingFaceTokenCounter:
    return HuggingFaceTokenCounter.from_file(embedder_tokenizer_path)


@pytest.mark.parametrize(("text", "tokens"), [("hello world", 3), ("valve V-12", 7)])
def test_counts_match_the_prompt_tokens_reported_by_the_model(
    counter: HuggingFaceTokenCounter, text: str, tokens: int
) -> None:
    # Docker Model Runner reported these prompt_tokens for ai/qwen3-embedding:0.6b.
    assert counter.count(text) == tokens


def test_a_long_table_is_cut_below_the_physical_batch(
    counter: HuggingFaceTokenCounter,
) -> None:
    table = "\n".join(f"| Spark plug {n} | SP-{n:04d} | 25 |" for n in range(800))

    truncated = counter.truncate(table, 2048)

    # Retokenizing the prefix can merge its last characters, so allow two tokens.
    assert 2046 <= counter.count(truncated) <= 2048
    assert table.startswith(truncated)
