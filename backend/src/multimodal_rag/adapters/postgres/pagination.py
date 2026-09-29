"""Opaque cursors for keyset pagination.

A cursor carries the sort key of the last row of a page, encoded so clients treat it
as an opaque token instead of building their own.
"""

import base64
from collections.abc import Callable

from multimodal_rag.ingestion.errors import InvalidCursorError

_SEPARATOR = "|"


def encode_cursor(*parts: str) -> str:
    """Encode the sort key of the last row of a page.

    Args:
        parts: Components of the sort key, in order.

    Returns:
        A URL-safe token.
    """
    return base64.urlsafe_b64encode(_SEPARATOR.join(parts).encode()).decode()


def decode_cursor[T](cursor: str, parse: Callable[[list[str]], T]) -> T:
    """Decode a cursor produced by ``encode_cursor``.

    Args:
        cursor: Token sent back by the client.
        parse: Turns the components of the sort key into typed values, raising
            ``ValueError`` when they are malformed or have the wrong count.

    Returns:
        The typed sort key.

    Raises:
        InvalidCursorError: If the token is not a cursor this API issued.
    """
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        return parse(decoded.split(_SEPARATOR))
    except ValueError as error:  # also covers bad base64 and bad UTF-8
        raise InvalidCursorError("The cursor is not valid") from error
