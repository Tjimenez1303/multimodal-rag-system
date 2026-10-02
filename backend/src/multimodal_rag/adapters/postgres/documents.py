"""PostgreSQL persistence of documents."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag.adapters.postgres.engine import connect, transaction
from multimodal_rag.adapters.postgres.pagination import decode_cursor, encode_cursor
from multimodal_rag.adapters.postgres.tables import documents, ingestion_jobs
from multimodal_rag.ingestion.domain import Document, JobStatus
from multimodal_rag.ingestion.errors import (
    DocumentNotFoundError,
    IngestionInProgressError,
)
from multimodal_rag.ingestion.ports import Page


class PostgresDocumentRepository:
    """Stores documents with one row per content fingerprint.

    Args:
        engine: Engine of the current process.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def register(self, document: Document) -> tuple[Document, bool]:
        """Store a document unless one with the same fingerprint exists.

        The unique fingerprint makes concurrent uploads of identical content resolve
        to a single row without application locks.

        Args:
            document: Document to store.

        Returns:
            The stored document and ``True``, or the existing document and ``False``.
        """
        # Insert the row, doing nothing when the fingerprint is already stored
        statement = (
            insert(documents)
            .values(**_values(document))
            .on_conflict_do_nothing(index_elements=[documents.c.sha256])
            .returning(documents.c.id)
        )
        async with transaction(self._engine) as connection:
            # A new row means the document is new
            inserted = (await connection.execute(statement)).scalar_one_or_none()
            if inserted is not None:
                return document, True

            # Otherwise return the document stored earlier with the same fingerprint
            existing = await connection.execute(
                sa.select(documents).where(documents.c.sha256 == document.sha256)
            )
            return _document(existing.mappings().one()), False

    async def get(self, document_id: uuid.UUID) -> Document:
        """Return a document by id.

        Args:
            document_id: Id of the document.

        Returns:
            The stored document.

        Raises:
            DocumentNotFoundError: If no document has this id.
        """
        # Read the row, failing with not found when there is none
        query = sa.select(documents).where(documents.c.id == document_id)
        async with connect(self._engine) as connection:
            row = (await connection.execute(query)).mappings().one_or_none()
        if row is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return _document(row)

    async def get_many(self, document_ids: Sequence[uuid.UUID]) -> tuple[Document, ...]:
        """Return several documents with one query.

        Args:
            document_ids: Ids of the documents.

        Returns:
            The stored documents, in no particular order. Unknown ids are skipped.
        """
        # No ids, no query
        if not document_ids:
            return ()
        query = sa.select(documents).where(documents.c.id.in_(document_ids))
        async with connect(self._engine) as connection:
            rows = (await connection.execute(query)).mappings().all()
        return tuple(_document(row) for row in rows)

    async def delete(self, document_id: uuid.UUID) -> None:
        """Delete a document, whose rows cascade to its jobs and elements.

        The document row is locked before its jobs are checked. A concurrent upload
        that enqueues a job either commits first, and is seen by the check, or waits
        on the lock and then finds no document.

        Args:
            document_id: Id of the document.

        Raises:
            DocumentNotFoundError: If no document has this id.
            IngestionInProgressError: If a job of the document is pending or
                processing.
        """
        # Lock the document row so no upload can enqueue a job meanwhile
        locked = (
            sa.select(documents.c.id)
            .where(documents.c.id == document_id)
            .with_for_update()
        )

        # Whether the document has a pending or processing job
        active = sa.select(
            sa.exists().where(
                ingestion_jobs.c.document_id == document_id,
                ingestion_jobs.c.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
            )
        )
        async with transaction(self._engine) as connection:
            # Check both conditions inside the transaction that holds the lock
            if (await connection.execute(locked)).scalar_one_or_none() is None:
                raise DocumentNotFoundError(f"Document {document_id} not found")
            if (await connection.execute(active)).scalar_one():
                raise IngestionInProgressError(
                    f"Document {document_id} is being ingested"
                )

            # Delete the row; foreign keys cascade to jobs, elements and relationships
            await connection.execute(
                sa.delete(documents).where(documents.c.id == document_id)
            )

    async def list_page(self, *, limit: int, cursor: str | None) -> Page[Document]:
        """Return documents newest first.

        Args:
            limit: Largest number of documents to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            One page of documents.

        Raises:
            InvalidCursorError: If the cursor was not issued by this repository.
        """
        # Newest first, with the id breaking ties between equal timestamps
        query = sa.select(documents).order_by(
            documents.c.created_at.desc(), documents.c.id.desc()
        )
        if cursor is not None:
            # Continue after the last row of the previous page
            created_at, document_id = decode_cursor(cursor, _position)
            query = query.where(
                sa.tuple_(documents.c.created_at, documents.c.id)
                < sa.tuple_(sa.literal(created_at), sa.literal(document_id))
            )
        async with connect(self._engine) as connection:
            # Read one row more than asked to know whether another page exists
            rows = (await connection.execute(query.limit(limit + 1))).mappings().all()
        items = tuple(_document(row) for row in rows[:limit])
        next_cursor = None

        # The cursor encodes the sort key of the last row returned
        if len(rows) > limit:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at.isoformat(), str(last.id))
        return Page(items=items, next_cursor=next_cursor)


def _position(parts: list[str]) -> tuple[datetime, uuid.UUID]:
    created_at, document_id = parts
    return datetime.fromisoformat(created_at), uuid.UUID(document_id)


def _values(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "sha256": document.sha256,
        "file_name": document.file_name,
        "size_bytes": document.size_bytes,
        "page_count": document.page_count,
        "blob_key": document.blob_key,
        "created_at": document.created_at,
    }


def _document(row: sa.RowMapping) -> Document:
    return Document(
        id=row["id"],
        sha256=row["sha256"],
        file_name=row["file_name"],
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        blob_key=row["blob_key"],
        created_at=row["created_at"],
    )
