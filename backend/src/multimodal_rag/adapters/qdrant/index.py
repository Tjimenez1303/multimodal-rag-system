"""``VectorIndex`` on Qdrant with dense vectors and server-side BM25.

Each point carries a named dense vector and a named sparse vector that Qdrant computes
with its BM25 inference from the unit's contextualized text. Hybrid search prefetches
both and fuses them with Reciprocal Rank Fusion, then scores the fused points again on
the dense side alone, so every hit also carries its cosine similarity to the query.
Points stay hidden (``visible=false``) until their job completes, and their payload is
validated when it is read back.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from itertools import batched
from typing import Any, Self

import httpx
import pydantic
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from multimodal_rag.adapters.provider_errors import status_error, transport_error
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    PagedBox,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.ingestion.ports import SearchHit
from multimodal_rag.shared.errors import DataInconsistencyError, ProviderResponseError
from multimodal_rag.shared.resilience import RetryPolicy, call_with_retry

SERVICE = "vector index"
DENSE = "dense"
BM25 = "bm25"
BM25_MODEL = "qdrant/bm25"
# Language-neutral analysis: the same terms match in English and Spanish, and part
# numbers match exactly because nothing is stemmed or dropped as a stopword.
BM25_OPTIONS = models.Bm25Config(
    lowercase=True,
    ascii_folding=True,
    stemmer=models.DisabledStemmerParams(type=models.NoStemmer.NONE),
    stopwords=models.StopwordsSet(languages=[], custom=[]),
)
PAYLOAD_INDEXES = {
    "document_id": models.PayloadSchemaType.UUID,
    "unit_type": models.PayloadSchemaType.KEYWORD,
    "pages": models.PayloadSchemaType.INTEGER,
    "visible": models.PayloadSchemaType.BOOL,
}
# Each side of a hybrid query returns this many times the final limit before fusion.
PREFETCH_FACTOR = 2
# Points per upsert request, which keeps each request small on long documents.
UPSERT_BATCH = 64
_NOT_FOUND = 404
_CONFLICT = 409


class _Box(pydantic.BaseModel):
    page: int
    left: float
    top: float
    right: float
    bottom: float


class UnitPayload(pydantic.BaseModel):
    """Payload stored with every point, one field per retrieval unit attribute.

    Attributes:
        document_id: Document the unit belongs to.
        unit_type: Text, table or figure unit.
        text: Unit text for display.
        heading_path: Section headings in scope.
        pages: Pages the unit spans.
        element_ids: Source elements.
        boxes: Positions of the source elements.
        figure_ids: Related images.
        image_key: Storage key of the crop, for figure units.
        visible: Whether the job that wrote the unit completed.
    """

    document_id: uuid.UUID
    unit_type: UnitType
    text: str
    heading_path: list[str]
    pages: list[int]
    element_ids: list[uuid.UUID]
    boxes: list[_Box]
    figure_ids: list[uuid.UUID]
    image_key: str | None
    visible: bool = False

    @classmethod
    def of(cls, unit: RetrievalUnit) -> Self:
        """Build the hidden payload of a unit.

        Args:
            unit: Unit to store.

        Returns:
            The payload, with ``visible`` false.
        """
        return cls(
            document_id=unit.document_id,
            unit_type=unit.unit_type,
            text=unit.text,
            heading_path=list(unit.heading_path),
            pages=list(unit.pages),
            element_ids=list(unit.element_ids),
            boxes=[
                _Box(
                    page=box.page,
                    left=box.bbox.left,
                    top=box.bbox.top,
                    right=box.bbox.right,
                    bottom=box.bbox.bottom,
                )
                for box in unit.boxes
            ],
            figure_ids=list(unit.figure_ids),
            image_key=unit.image_key,
        )

    def to_unit(self, point_id: models.ExtendedPointId) -> RetrievalUnit:
        """Rebuild the unit stored under a point.

        Args:
            point_id: Id of the point, which is the unit id.

        Returns:
            The retrieval unit.
        """
        return RetrievalUnit(
            id=uuid.UUID(str(point_id)),
            document_id=self.document_id,
            unit_type=self.unit_type,
            text=self.text,
            heading_path=tuple(self.heading_path),
            pages=tuple(self.pages),
            element_ids=tuple(self.element_ids),
            boxes=tuple(
                PagedBox(
                    page=box.page,
                    bbox=BoundingBox(
                        left=box.left, top=box.top, right=box.right, bottom=box.bottom
                    ),
                )
                for box in self.boxes
            ),
            figure_ids=tuple(self.figure_ids),
            image_key=self.image_key,
        )


class QdrantVectorIndex:
    """Stores retrieval units in one Qdrant collection.

    Args:
        client: Client created with the configured URL and timeout.
        collection: Name of the collection.
        dimensions: Length of the dense vectors.
        retry: Retry policy for transient failures.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        collection: str,
        dimensions: int,
        retry: RetryPolicy,
    ) -> None:
        self._client = client
        self.collection = collection
        self._dimensions = dimensions
        self._retry = retry

    async def ensure_collection(self) -> None:
        """Create the collection and its payload indexes when missing.

        Raises:
            ProviderUnavailableError: If Qdrant stays unreachable after retries.
            ProviderTimeoutError: If Qdrant keeps timing out after retries.
            ProviderResponseError: If Qdrant rejects the request.
        """
        if not await self._call(
            lambda: self._client.collection_exists(self.collection)
        ):
            await self._call(self._create_collection)
        for field, schema in PAYLOAD_INDEXES.items():
            await self._call(
                partial(
                    self._client.create_payload_index,
                    self.collection,
                    field_name=field,
                    field_schema=schema,
                    wait=True,
                )
            )

    async def upsert_units(
        self, units: Sequence[RetrievalUnit], vectors: Sequence[Sequence[float]]
    ) -> None:
        """Write units with their dense vectors, hidden from search.

        Args:
            units: Units to write. Their ids make a second write overwrite the first.
            vectors: Dense vector of each unit, in the same order.

        Raises:
            ProviderUnavailableError: If Qdrant stays unreachable after retries.
            ProviderTimeoutError: If Qdrant keeps timing out after retries.
            ProviderResponseError: If Qdrant rejects the request.
        """
        points = [
            models.PointStruct(
                id=str(unit.id),
                vector={
                    DENSE: list(vector),
                    BM25: _document(unit.embedding_text),
                },
                payload=UnitPayload.of(unit).model_dump(mode="json"),
            )
            for unit, vector in zip(units, vectors, strict=True)
        ]
        for batch in batched(points, UPSERT_BATCH, strict=False):
            await self._call(
                partial(
                    self._client.upsert, self.collection, points=list(batch), wait=True
                )
            )

    async def publish(self, document_id: uuid.UUID) -> None:
        """Make every unit of a document visible to search.

        Args:
            document_id: Document whose units are published.

        Raises:
            ProviderUnavailableError: If Qdrant stays unreachable after retries.
            ProviderTimeoutError: If Qdrant keeps timing out after retries.
            ProviderResponseError: If Qdrant rejects the request.
        """
        await self._call(
            lambda: self._client.set_payload(
                self.collection,
                payload={"visible": True},
                points=_of_document(document_id),
                wait=True,
            )
        )

    async def delete_document(self, document_id: uuid.UUID) -> None:
        """Remove every unit of a document.

        Args:
            document_id: Document whose units are removed.

        Raises:
            ProviderUnavailableError: If Qdrant stays unreachable after retries.
            ProviderTimeoutError: If Qdrant keeps timing out after retries.
            ProviderResponseError: If Qdrant rejects the request.
        """
        await self._call(
            lambda: self._client.delete(
                self.collection,
                points_selector=models.FilterSelector(filter=_of_document(document_id)),
                wait=True,
            )
        )

    async def search_hybrid(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[SearchHit]:
        """Return visible units ranked by fused dense and keyword relevance.

        Args:
            query_text: Query for the keyword side.
            query_vector: Dense vector of the query.
            limit: Largest number of hits.
            document_ids: Only units of these documents, when set.

        Returns:
            The hits, best first, each with its dense cosine similarity. A
            collection that does not exist yet returns no hits.

        Raises:
            ProviderUnavailableError: If Qdrant stays unreachable after retries.
            ProviderTimeoutError: If Qdrant keeps timing out after retries.
            ProviderResponseError: If Qdrant rejects the request.
            DataInconsistencyError: If a stored payload is invalid, or a fused point
                has no dense score.
        """
        conditions: list[models.Condition] = [
            models.FieldCondition(key="visible", match=models.MatchValue(value=True))
        ]
        if document_ids is not None:
            conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=[str(i) for i in document_ids]),
                )
            )
        visible = models.Filter(must=conditions)
        prefetch = [
            models.Prefetch(
                query=list(query_vector),
                using=DENSE,
                filter=visible,
                limit=limit * PREFETCH_FACTOR,
            ),
            models.Prefetch(
                query=_document(query_text),
                using=BM25,
                filter=visible,
                limit=limit * PREFETCH_FACTOR,
            ),
        ]
        fused = await self._call(
            partial(
                self._points_or_none,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
        )
        if not fused:
            return []
        units = [_unit(point.id, point.payload) for point in fused]
        similarities = await self._similarities(query_vector, units)
        return [
            SearchHit(unit=unit, score=point.score, similarity=similarities[unit.id])
            for unit, point in zip(units, fused, strict=True)
        ]

    async def _similarities(
        self, query_vector: Sequence[float], units: Sequence[RetrievalUnit]
    ) -> dict[uuid.UUID, float]:
        # RRF scores only reflect ranks, so the dense side scores the fused ids again,
        # exactly, to give each hit a similarity that is comparable across queries.
        ids: list[models.ExtendedPointId] = [str(unit.id) for unit in units]
        scored = await self._call(
            partial(
                self._points_or_none,
                query=list(query_vector),
                using=DENSE,
                query_filter=models.Filter(must=[models.HasIdCondition(has_id=ids)]),
                search_params=models.SearchParams(exact=True),
                limit=len(ids),
                with_payload=False,
            )
        )
        similarities = {uuid.UUID(str(point.id)): point.score for point in scored or []}
        missing = [unit.id for unit in units if unit.id not in similarities]
        if missing:
            raise DataInconsistencyError(
                f"The {SERVICE} returned no dense score for points {missing}"
            )
        return similarities

    async def _points_or_none(self, **query: Any) -> list[models.ScoredPoint] | None:
        try:
            response = await self._client.query_points(self.collection, **query)
        except UnexpectedResponse as error:
            # No document was ever indexed, so there is nothing to find.
            if error.status_code == _NOT_FOUND:
                return None
            raise
        return response.points

    async def _create_collection(self) -> None:
        try:
            await self._client.create_collection(
                self.collection,
                vectors_config={
                    DENSE: models.VectorParams(
                        size=self._dimensions, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    BM25: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        except UnexpectedResponse as error:
            # Another worker created the collection between the check and this call.
            if error.status_code != _CONFLICT:
                raise

    async def _call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        async def attempt() -> T:
            try:
                return await operation()
            except ResponseHandlingException as error:
                # The client wraps both transport failures and answers it cannot parse.
                if isinstance(error.source, httpx.TransportError):
                    raise transport_error(error.source, service=SERVICE) from error
                message = f"The {SERVICE} answered something it could not parse"
                raise ProviderResponseError(message) from error
            except UnexpectedResponse as error:
                raise status_error(error.status_code, service=SERVICE) from error

        return await call_with_retry(self._retry, attempt)


def _document(text: str) -> models.Document:
    return models.Document(text=text, model=BM25_MODEL, options=BM25_OPTIONS)


def _of_document(document_id: uuid.UUID) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="document_id", match=models.MatchValue(value=str(document_id))
            )
        ]
    )


def _unit(
    point_id: models.ExtendedPointId, payload: dict[str, Any] | None
) -> RetrievalUnit:
    try:
        return UnitPayload.model_validate(payload).to_unit(point_id)
    except pydantic.ValidationError as error:
        raise DataInconsistencyError(
            f"Point {point_id} of the {SERVICE} has an invalid payload"
        ) from error
