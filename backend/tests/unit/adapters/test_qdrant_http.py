"""Requests and error mapping of the Qdrant index, with its REST API mocked."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx
import stamina
from qdrant_client import AsyncQdrantClient

from multimodal_rag.adapters.qdrant.index import QdrantVectorIndex, UnitPayload
from multimodal_rag.ingestion.domain import (
    BoundingBox,
    PagedBox,
    RetrievalUnit,
    UnitType,
)
from multimodal_rag.shared.errors import (
    DataInconsistencyError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from multimodal_rag.shared.resilience import RetryPolicy

URL = "http://qdrant.test:6333"
COLLECTION = f"{URL}/collections/units"
OK = {"result": True, "status": "ok", "time": 0.0}
RETRY = RetryPolicy(
    attempts=2,
    initial_wait_seconds=0.01,
    max_wait_seconds=0.01,
    jitter_seconds=0,
    timeout_seconds=None,
)


@pytest.fixture(autouse=True)
def fast_retries() -> Iterator[None]:
    stamina.set_testing(True, attempts=2)
    yield
    stamina.set_testing(False)


@pytest.fixture
async def index() -> AsyncIterator[QdrantVectorIndex]:
    client = AsyncQdrantClient(url=URL, timeout=1, check_compatibility=False)
    yield QdrantVectorIndex(client, collection="units", dimensions=4, retry=RETRY)
    await client.close()


def exists(value: bool) -> httpx.Response:
    return httpx.Response(
        200, json={"result": {"exists": value}, "status": "ok", "time": 0.0}
    )


@respx.mock
async def test_a_collection_created_meanwhile_by_another_worker_is_reused(
    index: QdrantVectorIndex,
) -> None:
    respx.get(f"{COLLECTION}/exists").mock(return_value=exists(False))
    created = respx.put(COLLECTION).mock(
        return_value=httpx.Response(409, json={"status": {"error": "exists"}})
    )
    indexes = respx.put(f"{COLLECTION}/index").mock(
        return_value=httpx.Response(
            200, json=OK | {"result": {"operation_id": 1, "status": "completed"}}
        )
    )

    await index.ensure_collection()

    assert created.call_count == 1
    assert indexes.call_count == 4


@pytest.mark.parametrize(
    ("reply", "error", "calls"),
    [
        (httpx.Response(503), ProviderUnavailableError, 2),
        (httpx.ReadTimeout("slow"), ProviderTimeoutError, 2),
        (
            httpx.Response(400, json={"status": {"error": "bad"}}),
            ProviderResponseError,
            1,
        ),
    ],
    ids=["5xx", "timeout", "rejected"],
)
@respx.mock
async def test_failures_map_to_provider_errors_and_only_transient_ones_retry(
    index: QdrantVectorIndex,
    reply: httpx.Response | Exception,
    error: type[Exception],
    calls: int,
) -> None:
    route = respx.get(f"{COLLECTION}/exists").mock(side_effect=[reply] * calls)

    with pytest.raises(error):
        await index.ensure_collection()

    assert route.call_count == calls


@respx.mock
async def test_any_other_failure_to_create_the_collection_is_reported(
    index: QdrantVectorIndex,
) -> None:
    respx.get(f"{COLLECTION}/exists").mock(return_value=exists(False))
    respx.put(COLLECTION).mock(
        return_value=httpx.Response(400, json={"status": {"error": "bad config"}})
    )

    with pytest.raises(ProviderResponseError):
        await index.ensure_collection()


async def test_writing_no_units_sends_nothing(index: QdrantVectorIndex) -> None:
    with respx.mock(assert_all_called=False) as router:
        await index.upsert_units([], [])

    assert router.calls.call_count == 0


@respx.mock
async def test_an_answer_that_does_not_parse_is_rejected_without_retry(
    index: QdrantVectorIndex,
) -> None:
    route = respx.get(f"{COLLECTION}/exists").mock(
        return_value=httpx.Response(200, json={"result": "not an object"})
    )

    with pytest.raises(ProviderResponseError):
        await index.ensure_collection()

    assert route.call_count == 1


def unit(number: int) -> RetrievalUnit:
    return RetrievalUnit(
        id=uuid.UUID(int=number + 1),
        document_id=uuid.UUID(int=0),
        unit_type=UnitType.TEXT,
        text=f"unit {number}",
        heading_path=(),
        pages=(1,),
        element_ids=(uuid.UUID(int=10_000 + number),),
        boxes=(PagedBox(page=1, bbox=BoundingBox(left=1, top=1, right=2, bottom=2)),),
    )


@respx.mock
async def test_units_are_written_in_batches_of_64(index: QdrantVectorIndex) -> None:
    route = respx.put(f"{COLLECTION}/points").mock(
        return_value=httpx.Response(
            200, json=OK | {"result": {"operation_id": 1, "status": "completed"}}
        )
    )
    units = [unit(n) for n in range(130)]

    await index.upsert_units(units, [[0.0, 0.0, 0.0, 1.0]] * len(units))

    sizes = [len(json.loads(call.request.content)["points"]) for call in route.calls]
    assert sizes == [64, 64, 2]


@respx.mock
async def test_a_stored_payload_of_the_wrong_shape_is_an_inconsistency(
    index: QdrantVectorIndex,
) -> None:
    point = {"id": str(uuid.UUID(int=1)), "version": 1, "score": 0.5}
    respx.post(f"{COLLECTION}/points/query").respond(
        json=OK | {"result": {"points": [point | {"payload": {"text": "x"}}]}}
    )

    with pytest.raises(DataInconsistencyError):
        await index.search_hybrid(query_text="x", query_vector=[0.0] * 4, limit=5)


def point(number: int, score: float) -> dict[str, object]:
    return {"id": str(unit(number).id), "version": 1, "score": score}


def payload(number: int) -> dict[str, object]:
    return UnitPayload.of(unit(number)).model_dump(mode="json") | {"visible": True}


@respx.mock
async def test_a_missing_collection_answers_no_hits_without_retry(
    index: QdrantVectorIndex,
) -> None:
    route = respx.post(f"{COLLECTION}/points/query").respond(
        404, json={"status": {"error": "Collection `units` doesn't exist!"}}
    )

    hits = await index.search_hybrid(query_text="x", query_vector=[0.0] * 4, limit=5)

    assert hits == []
    assert route.call_count == 1


@respx.mock
async def test_deleting_from_a_missing_collection_deletes_nothing_without_retry(
    index: QdrantVectorIndex,
) -> None:
    route = respx.post(f"{COLLECTION}/points/delete").respond(
        404, json={"status": {"error": "Collection `units` doesn't exist!"}}
    )

    await index.delete_document(uuid.uuid4())

    assert route.call_count == 1


@respx.mock
async def test_similarities_are_scored_exactly_for_the_fused_ids(
    index: QdrantVectorIndex,
) -> None:
    fused = OK | {
        "result": {
            "points": [
                point(1, 0.5) | {"payload": payload(1)},
                point(2, 0.33) | {"payload": payload(2)},
            ]
        }
    }
    dense = OK | {"result": {"points": [point(2, 0.71), point(1, 0.42)]}}
    route = respx.post(f"{COLLECTION}/points/query").mock(
        side_effect=[httpx.Response(200, json=fused), httpx.Response(200, json=dense)]
    )

    hits = await index.search_hybrid(
        query_text="x", query_vector=[0.1, 0.2, 0.3, 0.4], limit=5
    )

    assert [(hit.unit, hit.score, hit.similarity) for hit in hits] == [
        (unit(1), 0.5, 0.42),
        (unit(2), 0.33, 0.71),
    ]
    rescoring = json.loads(route.calls.last.request.content)
    assert rescoring["query"] == {"nearest": [0.1, 0.2, 0.3, 0.4]}
    assert rescoring["using"] == "dense"
    assert rescoring["limit"] == 2
    assert rescoring["params"]["exact"] is True
    assert rescoring["filter"]["must"] == [
        {"has_id": [str(unit(1).id), str(unit(2).id)]}
    ]


@respx.mock
async def test_a_fused_hit_without_a_similarity_is_an_inconsistency(
    index: QdrantVectorIndex,
) -> None:
    fused = OK | {"result": {"points": [point(1, 0.5) | {"payload": payload(1)}]}}
    empty = OK | {"result": {"points": []}}
    respx.post(f"{COLLECTION}/points/query").mock(
        side_effect=[httpx.Response(200, json=fused), httpx.Response(200, json=empty)]
    )

    with pytest.raises(DataInconsistencyError):
        await index.search_hybrid(query_text="x", query_vector=[0.0] * 4, limit=5)


@respx.mock
async def test_no_fused_hit_needs_no_similarity_query(
    index: QdrantVectorIndex,
) -> None:
    route = respx.post(f"{COLLECTION}/points/query").respond(
        json=OK | {"result": {"points": []}}
    )

    assert (
        await index.search_hybrid(query_text="x", query_vector=[0.0] * 4, limit=5) == []
    )
    assert route.call_count == 1
