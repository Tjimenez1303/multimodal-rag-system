"""PostgreSQL persistence of extracted elements and their relationships."""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from multimodal_rag.adapters.postgres.engine import connect, transaction
from multimodal_rag.adapters.postgres.job_queue import lock_leased_job
from multimodal_rag.adapters.postgres.pagination import decode_cursor, encode_cursor
from multimodal_rag.adapters.postgres.tables import (
    element_relationships,
    extracted_elements,
)
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    DescriptionStatus,
    ElementKind,
    ElementRelationship,
    ExtractedElement,
    RelationshipKind,
    TextOrigin,
)
from multimodal_rag.ingestion.errors import ElementNotFoundError
from multimodal_rag.ingestion.ports import Page
from multimodal_rag.shared.errors import DataInconsistencyError


class PostgresElementRepository:
    """Stores the elements of each document, replaced as a whole on every attempt.

    Args:
        engine: Engine of the current process.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def replace_for_document(
        self,
        *,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        document_id: uuid.UUID,
        elements: Sequence[ExtractedElement],
        relationships: Sequence[ElementRelationship],
    ) -> None:
        """Replace every element of a document in one transaction.

        The job row stays locked until the transaction ends, so the replacement is
        fenced by the lease: it either lands whole under the current attempt or not
        at all.

        Args:
            job_id: Job whose attempt writes the elements.
            lease_token: Token of the attempt.
            document_id: Document whose elements are replaced.
            elements: New elements of the document.
            relationships: Links between the new elements.

        Raises:
            LeaseLostError: If the job's lease token is no longer current.
            DataInconsistencyError: If the job ingests another document.
        """
        async with transaction(self._engine) as connection:
            job = await lock_leased_job(connection, job_id, lease_token)
            # The lease covers only the document of its own job.
            if job.document_id != document_id:
                raise DataInconsistencyError(
                    f"Job {job_id} does not ingest document {document_id}"
                )
            await connection.execute(
                sa.delete(extracted_elements).where(
                    extracted_elements.c.document_id == document_id
                )
            )
            if elements:
                await connection.execute(
                    sa.insert(extracted_elements), [_values(e) for e in elements]
                )
            if relationships:
                await connection.execute(
                    sa.insert(element_relationships),
                    [_link_values(document_id, link) for link in relationships],
                )

    async def list_page(
        self,
        *,
        document_id: uuid.UUID,
        page_number: int | None,
        kind: ElementKind | None,
        limit: int,
        cursor: str | None,
    ) -> Page[ExtractedElement]:
        """Return the elements of a document in reading order, optionally filtered.

        Args:
            document_id: Document whose elements are listed.
            page_number: Only elements of this 1-based page, when set.
            kind: Only elements of this kind, when set.
            limit: Largest number of elements to return.
            cursor: Cursor returned by the previous page, or ``None`` for the first.

        Returns:
            One page of elements.

        Raises:
            InvalidCursorError: If the cursor was not issued by this repository.
        """
        query = (
            sa.select(extracted_elements)
            .where(extracted_elements.c.document_id == document_id)
            .order_by(extracted_elements.c.reading_order)
        )
        if page_number is not None:
            query = query.where(extracted_elements.c.page == page_number)
        if kind is not None:
            query = query.where(extracted_elements.c.kind == kind.value)
        if cursor is not None:
            query = query.where(
                extracted_elements.c.reading_order > decode_cursor(cursor, _position)
            )
        async with connect(self._engine) as connection:
            rows = (await connection.execute(query.limit(limit + 1))).mappings().all()
        items = tuple(_element(row) for row in rows[:limit])
        next_cursor = (
            encode_cursor(str(items[-1].reading_order)) if len(rows) > limit else None
        )
        return Page(items=items, next_cursor=next_cursor)

    async def relationships_for(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ElementRelationship, ...]:
        """Return the relationships that touch the given elements.

        Args:
            element_ids: Elements at either end of the relationships.

        Returns:
            Every relationship whose source or target is one of the elements.
        """
        query = sa.select(element_relationships).where(
            sa.or_(
                element_relationships.c.source_id.in_(element_ids),
                element_relationships.c.target_id.in_(element_ids),
            )
        )
        async with connect(self._engine) as connection:
            rows = (await connection.execute(query)).mappings().all()
        return tuple(
            ElementRelationship(
                source_id=row["source_id"],
                target_id=row["target_id"],
                kind=RelationshipKind(row["kind"]),
                score=row["score"],
            )
            for row in rows
        )

    async def get(
        self, *, document_id: uuid.UUID, element_id: uuid.UUID
    ) -> ExtractedElement:
        """Return one element of a document.

        Args:
            document_id: Document the element belongs to.
            element_id: Id of the element.

        Returns:
            The stored element.

        Raises:
            ElementNotFoundError: If the document has no such element.
        """
        query = sa.select(extracted_elements).where(
            extracted_elements.c.document_id == document_id,
            extracted_elements.c.id == element_id,
        )
        async with connect(self._engine) as connection:
            row = (await connection.execute(query)).mappings().one_or_none()
        if row is None:
            raise ElementNotFoundError(f"Element {element_id} not found")
        return _element(row)

    async def get_many(
        self, element_ids: Sequence[uuid.UUID]
    ) -> tuple[ExtractedElement, ...]:
        """Return several elements with one query, whatever their documents.

        Args:
            element_ids: Ids of the elements.

        Returns:
            The stored elements, in no particular order. Unknown ids are skipped.
        """
        if not element_ids:
            return ()
        query = sa.select(extracted_elements).where(
            extracted_elements.c.id.in_(element_ids)
        )
        async with connect(self._engine) as connection:
            rows = (await connection.execute(query)).mappings().all()
        return tuple(_element(row) for row in rows)


def _position(parts: list[str]) -> int:
    [reading_order] = parts
    return int(reading_order)


def _values(element: ExtractedElement) -> dict[str, Any]:
    return {
        "id": element.id,
        "document_id": element.document_id,
        "kind": element.kind.value,
        "page": element.page,
        "bbox_left": element.bbox.left,
        "bbox_top": element.bbox.top,
        "bbox_right": element.bbox.right,
        "bbox_bottom": element.bbox.bottom,
        "reading_order": element.reading_order,
        "origin": element.origin.value,
        "heading_level": element.heading_level,
        "text": element.text,
        "table_rows": None if element.table is None else list(element.table),
        "confidence": element.confidence,
        "image_key": element.image_key,
        "image_class": element.image_class,
        "labels": list(element.labels),
        "description": element.description,
        "description_status": (
            None
            if element.description_status is None
            else element.description_status.value
        ),
        "unverified_identifiers": list(element.unverified_identifiers),
        "is_decorative": element.is_decorative,
    }


def _link_values(document_id: uuid.UUID, link: ElementRelationship) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "source_id": link.source_id,
        "target_id": link.target_id,
        "kind": link.kind.value,
        "score": link.score,
    }


def _element(row: sa.RowMapping) -> ExtractedElement:
    table = row["table_rows"]
    status = row["description_status"]
    return ExtractedElement(
        id=row["id"],
        document_id=row["document_id"],
        kind=ElementKind(row["kind"]),
        page=row["page"],
        bbox=BoundingBox(
            left=row["bbox_left"],
            top=row["bbox_top"],
            right=row["bbox_right"],
            bottom=row["bbox_bottom"],
        ),
        reading_order=row["reading_order"],
        origin=TextOrigin(row["origin"]),
        heading_level=row["heading_level"],
        text=row["text"],
        table=None if table is None else tuple(tuple(cells) for cells in table),
        confidence=row["confidence"],
        image_key=row["image_key"],
        image_class=row["image_class"],
        labels=tuple(row["labels"]),
        description=row["description"],
        description_status=None if status is None else DescriptionStatus(status),
        unverified_identifiers=tuple(row["unverified_identifiers"]),
        is_decorative=row["is_decorative"],
    )
