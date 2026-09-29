import pytest

from multimodal_rag.adapters.postgres.pagination import decode_cursor, encode_cursor
from multimodal_rag.ingestion.errors import InvalidCursorError


def pair(parts: list[str]) -> tuple[str, int]:
    name, number = parts
    return name, int(number)


def test_cursor_round_trips_its_typed_parts() -> None:
    assert decode_cursor(encode_cursor("page", "7"), pair) == ("page", 7)


@pytest.mark.parametrize(
    "cursor", ["%%%", "/w==", encode_cursor("only-one"), encode_cursor("page", "x")]
)
def test_foreign_or_damaged_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor, pair)
