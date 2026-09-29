import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import stamina
from qdrant_client import AsyncQdrantClient, models

from multimodal_rag.adapters.qdrant.index import QdrantVectorIndex
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    PagedBox,
    RetrievalUnit,
    UnitType,
    unit_id_for,
)
from multimodal_rag.shared.errors import ProviderUnavailableError
from multimodal_rag.shared.resilience import RetryPolicy

DIMENSIONS = 4
RETRY = RetryPolicy(
    attempts=2,
    initial_wait_seconds=0.01,
    max_wait_seconds=0.01,
    jitter_seconds=0,
    timeout_seconds=None,
)
BOX = PagedBox(page=3, bbox=BoundingBox(left=72, top=100, right=540, bottom=300))


@pytest.fixture
async def client(qdrant_url: str) -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(url=qdrant_url, timeout=10)
    yield client
    await client.close()


@pytest.fixture
async def index(client: AsyncQdrantClient) -> QdrantVectorIndex:
    index = QdrantVectorIndex(
        client,
        collection=f"units_{uuid.uuid4().hex}",
        dimensions=DIMENSIONS,
        retry=RETRY,
    )
    await index.ensure_collection()
    return index


def unit(
    document_id: uuid.UUID,
    key: str,
    text: str,
    *,
    unit_type: UnitType = UnitType.TEXT,
    image_key: str | None = None,
) -> RetrievalUnit:
    return RetrievalUnit(
        id=unit_id_for(document_sha256=document_id.hex * 2, unit_key=key),
        document_id=document_id,
        unit_type=unit_type,
        text=text,
        heading_path=("Ignition", "Magneto"),
        pages=(3,),
        element_ids=(uuid.uuid4(),),
        boxes=(BOX,),
        figure_ids=(uuid.uuid4(),) if unit_type is UnitType.TEXT else (),
        image_key=image_key,
    )


def vector(seed: int) -> list[float]:
    return [float(seed == n) for n in range(DIMENSIONS)]


def manual(document_id: uuid.UUID) -> list[RetrievalUnit]:
    return [
        unit(document_id, "text:1", "The magneto fires the spark plugs in order."),
        unit(document_id, "text:2", "Generators charge the battery while running."),
        unit(
            document_id,
            "figure:3",
            "Figure 4-2. Magneto circuit\nV-12 P-1\nA wiring diagram.",
            unit_type=UnitType.FIGURE,
            image_key="figures/x/y.png",
        ),
    ]


async def count(client: AsyncQdrantClient, index: QdrantVectorIndex) -> int:
    return (await client.count(index.collection, exact=True)).count


async def test_the_collection_has_dense_and_bm25_vectors_and_payload_indexes(
    client: AsyncQdrantClient, index: QdrantVectorIndex
) -> None:
    await index.ensure_collection()

    info = await client.get_collection(index.collection)

    vectors = info.config.params.vectors
    assert isinstance(vectors, dict)
    assert vectors["dense"].size == DIMENSIONS
    assert vectors["dense"].distance is models.Distance.COSINE
    sparse = info.config.params.sparse_vectors
    assert sparse is not None and sparse["bm25"].modifier is models.Modifier.IDF
    assert set(info.payload_schema) == {"document_id", "unit_type", "pages", "visible"}


async def test_units_are_hidden_until_published_and_upserts_are_idempotent(
    client: AsyncQdrantClient, index: QdrantVectorIndex
) -> None:
    document_id = uuid.uuid4()
    units = manual(document_id)
    vectors = [vector(n) for n in range(len(units))]

    for _ in range(2):
        await index.upsert_units(units, vectors)

    assert await count(client, index) == 3
    hidden = await index.search_hybrid(
        query_text="V-12", query_vector=vector(2), limit=5
    )
    assert hidden == []

    await index.publish(document_id)

    hits = await index.search_hybrid(query_text="V-12", query_vector=vector(0), limit=5)
    assert hits[0].unit == units[2]
    assert {hit.unit.id for hit in hits} <= {u.id for u in units}


async def test_search_is_limited_to_the_requested_documents(
    index: QdrantVectorIndex,
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    for document_id in (first, second):
        units = manual(document_id)
        await index.upsert_units(units, [vector(n) for n in range(len(units))])
        await index.publish(document_id)

    hits = await index.search_hybrid(
        query_text="magneto", query_vector=vector(0), limit=10, document_ids=[second]
    )

    assert hits and {hit.unit.document_id for hit in hits} == {second}


async def test_keyword_search_ignores_accents_and_case(
    index: QdrantVectorIndex,
) -> None:
    document_id = uuid.uuid4()
    spanish = unit(document_id, "text:1", "Tensión ELÉCTRICA en la máquina.")
    # The other unit wins on the dense side, so only keyword search can rank Spanish.
    other = unit(document_id, "text:2", "Generators charge the battery.")
    await index.upsert_units([spanish, other], [vector(0), vector(3)])
    await index.publish(document_id)

    hits = await index.search_hybrid(
        query_text="tension electrica maquina", query_vector=vector(3), limit=5
    )

    assert hits[0].unit.id == spanish.id


async def test_each_hit_carries_its_cosine_similarity_to_the_query(
    index: QdrantVectorIndex,
) -> None:
    document_id = uuid.uuid4()
    units = manual(document_id)
    await index.upsert_units(units, [vector(n) for n in range(len(units))])
    await index.publish(document_id)

    # Cosine of (3, 4, 0, 0) with the one-hot vectors 0, 1 and 2.
    hits = await index.search_hybrid(
        query_text="magneto", query_vector=[3.0, 4.0, 0.0, 0.0], limit=5
    )

    expected = {units[0].id: 0.6, units[1].id: 0.8, units[2].id: 0.0}
    assert {hit.unit.id for hit in hits} == set(expected)
    for hit in hits:
        assert hit.similarity == pytest.approx(expected[hit.unit.id], abs=1e-6)


async def test_a_collection_that_does_not_exist_yet_has_no_hits(
    client: AsyncQdrantClient,
) -> None:
    index = QdrantVectorIndex(
        client,
        collection=f"missing_{uuid.uuid4().hex}",
        dimensions=DIMENSIONS,
        retry=RETRY,
    )

    hits = await index.search_hybrid(
        query_text="magneto", query_vector=vector(0), limit=5
    )

    assert hits == []


async def test_an_identifier_reaches_the_top_hits_through_the_keyword_side(
    index: QdrantVectorIndex,
) -> None:
    document_id = uuid.uuid4()
    fillers = [
        unit(document_id, f"text:{n}", f"Generators charge the battery, note {n}.")
        for n in range(11)
    ]
    code = unit(document_id, "text:code", "Code SPL-480 means low oil pressure.")
    # Every filler is closer to the query vector than the unit with the code.
    await index.upsert_units([*fillers, code], [vector(0)] * len(fillers) + [vector(3)])
    await index.publish(document_id)

    hits = await index.search_hybrid(
        query_text="What is code SPL-480?", query_vector=vector(0), limit=8
    )

    [found] = [hit for hit in hits if hit.unit.id == code.id]
    assert found.similarity == pytest.approx(0.0, abs=1e-6)
    assert hits.index(found) < 8


async def test_deleting_a_document_removes_all_its_points(
    client: AsyncQdrantClient, index: QdrantVectorIndex
) -> None:
    kept, removed = uuid.uuid4(), uuid.uuid4()
    for document_id in (kept, removed):
        units = manual(document_id)
        await index.upsert_units(units, [vector(n) for n in range(len(units))])

    await index.delete_document(removed)

    assert await count(client, index) == 3


@pytest.fixture
def few_retries() -> Iterator[None]:
    stamina.set_testing(True, attempts=2)
    yield
    stamina.set_testing(False)


@pytest.mark.usefixtures("few_retries")
async def test_an_unreachable_index_is_reported_after_the_retry_budget() -> None:
    # The version check would run in a thread and warn about the refused connection.
    client = AsyncQdrantClient(
        url="http://127.0.0.1:9", timeout=1, check_compatibility=False
    )
    index = QdrantVectorIndex(
        client, collection="units", dimensions=DIMENSIONS, retry=RETRY
    )

    with pytest.raises(ProviderUnavailableError):
        await index.ensure_collection()

    await client.close()
