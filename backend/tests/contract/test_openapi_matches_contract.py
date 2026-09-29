"""The OpenAPI document the API serves agrees with the features' contracts."""

from typing import Any

import pytest

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.adapters.http.routes_ingestion import ingestion_router
from tests.contract.contract import PATHS, resolve

SERVED: dict[str, Any] = create_app(
    readiness_checks={}, routers=(ingestion_router, documents_router)
).openapi()
OPERATIONS = [
    (path, method)
    for path, item in SERVED["paths"].items()
    for method in item
    if method in {"get", "post", "put", "patch", "delete"}
]


def test_every_served_operation_is_in_the_contract() -> None:
    missing = [op for op in OPERATIONS if op[1] not in PATHS.get(op[0], {})]

    assert missing == []


@pytest.mark.parametrize(("path", "method"), OPERATIONS)
def test_operation_ids_and_statuses_match(path: str, method: str) -> None:
    served = SERVED["paths"][path][method]
    declared = PATHS[path][method]

    assert served["operationId"] == declared["operationId"]
    assert set(served["responses"]) == set(declared["responses"])


@pytest.mark.parametrize(("path", "method"), OPERATIONS)
def test_media_types_and_headers_match(path: str, method: str) -> None:
    served = SERVED["paths"][path][method]["responses"]
    declared = PATHS[path][method]["responses"]

    for status, contract_response in declared.items():
        expected = resolve(contract_response, path=path)
        if "content" in expected:
            assert set(served[status].get("content", {})) == set(expected["content"])
        assert set(served[status].get("headers", {})) == set(
            expected.get("headers", {})
        ), status


def test_problem_bodies_are_documented_as_problem_json() -> None:
    problem = SERVED["paths"]["/api/v1/documents"]["post"]["responses"]["413"]

    schema = problem["content"]["application/problem+json"]["schema"]

    assert schema == {"$ref": "#/components/schemas/Problem"}


@pytest.mark.parametrize(("path", "method"), OPERATIONS)
def test_parameters_match(path: str, method: str) -> None:
    served = SERVED["paths"][path][method].get("parameters", [])
    declared = PATHS[path][method].get("parameters", [])

    assert {(p["name"], p["in"]) for p in served} == {
        (resolve(p, path=path)["name"], resolve(p, path=path)["in"]) for p in declared
    }
