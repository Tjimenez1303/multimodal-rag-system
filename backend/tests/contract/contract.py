"""Validation of HTTP responses against the OpenAPI contracts of the features.

OpenAPI 3.1 schemas are JSON Schema 2020-12, so each response body is validated with
``Draft202012Validator``. Every contract is registered under its file URI, so the
relative ``$ref`` from one feature's contract into another's resolves as it does on
disk.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urldefrag, urljoin

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

SPECS = Path(__file__).resolve().parents[3] / "specs"
CONTRACT_FILES = (
    SPECS / "001-async-pdf-ingestion" / "contracts" / "openapi.yaml",
    SPECS / "002-grounded-question-answering" / "contracts" / "openapi.yaml",
    SPECS / "003-visual-chat-client" / "contracts" / "openapi.yaml",
    SPECS / "004-reranked-relevance-gate" / "contracts" / "openapi.yaml",
)
_CONTRACTS: dict[str, dict[str, Any]] = {
    path.as_uri(): yaml.safe_load(path.read_text()) for path in CONTRACT_FILES
}
_REGISTRY: Registry[Any] = Registry().with_resources(
    (uri, DRAFT202012.create_resource(contract)) for uri, contract in _CONTRACTS.items()
)
# Every operation of every contract, keyed by path template and method. A later
# feature may add a method to a path an earlier feature declared, or redefine one.
PATHS: dict[str, dict[str, Any]] = {}
_URI_BY_OPERATION: dict[tuple[str, str], str] = {}
for _uri, _contract in _CONTRACTS.items():
    for _path, _item in _contract["paths"].items():
        PATHS.setdefault(_path, {}).update(_item)
        _URI_BY_OPERATION.update({(_path, method): _uri for method in _item})


class HttpResponse(Protocol):
    """What the contract check reads from a test client response."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def json(self) -> Any: ...


def resolve(node: dict[str, Any], *, path: str, method: str) -> dict[str, Any]:
    """Follow ``$ref`` pointers until a concrete object is reached.

    Args:
        node: Object taken from the operation of ``path`` and ``method``.
        path: Path template of the operation.
        method: HTTP method in lowercase, which with the path names the contract
            file the pointers are relative to.
    """
    return _resolve_from(node, uri=_URI_BY_OPERATION[path, method])[0]


def _resolve_from(node: dict[str, Any], *, uri: str) -> tuple[dict[str, Any], str]:
    """Follow ``$ref`` pointers from the file at ``uri``.

    Returns:
        The concrete object and the URI of the file it lives in, which its own
        relative pointers are resolved against.
    """
    while "$ref" in node:
        target = urljoin(uri, node["$ref"])
        node = _REGISTRY.resolver(uri).lookup(target).contents
        uri = urldefrag(target).url
    return node, uri


def assert_matches_contract(response: HttpResponse, *, path: str, method: str) -> None:
    """Fail unless the status, media type and body are declared by the contract.

    Args:
        response: Response returned by the test client.
        path: Path template of the operation, as written in the contract.
        method: HTTP method in lowercase.
    """
    operation = PATHS[path][method]
    declared = operation["responses"]
    status = str(response.status_code)
    assert status in declared, f"{method.upper()} {path} does not declare {status}"
    response_object, uri = _resolve_from(
        declared[status], uri=_URI_BY_OPERATION[path, method]
    )
    content = response_object.get("content", {})
    if not content:
        assert response.headers["x-request-id"]
        return
    media_type = response.headers["content-type"].split(";")[0]
    assert media_type in content, f"{status} is not declared as {media_type}"
    schema = content[media_type]["schema"]
    pointer = schema["$ref"] if "$ref" in schema else None
    assert pointer is not None, "contract bodies are named components"
    validator = Draft202012Validator(
        # The pointer is local ("#/...") or relative to another contract file.
        {"$ref": urljoin(uri, pointer)},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(response.json())
    assert response.headers["x-request-id"]
