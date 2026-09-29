"""Validation of HTTP responses against the OpenAPI contracts of the features.

OpenAPI 3.1 schemas are JSON Schema 2020-12, so each response body is validated with
``Draft202012Validator``. Every contract is registered under its file URI, so the
relative ``$ref`` from one feature's contract into another's resolves as it does on
disk.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

SPECS = Path(__file__).resolve().parents[3] / "specs"
CONTRACT_FILES = (
    SPECS / "001-async-pdf-ingestion" / "contracts" / "openapi.yaml",
    SPECS / "002-grounded-question-answering" / "contracts" / "openapi.yaml",
)
_CONTRACTS: dict[str, dict[str, Any]] = {
    path.as_uri(): yaml.safe_load(path.read_text()) for path in CONTRACT_FILES
}
_REGISTRY: Registry[Any] = Registry().with_resources(
    (uri, DRAFT202012.create_resource(contract)) for uri, contract in _CONTRACTS.items()
)
# Every operation of every contract, keyed by path template.
PATHS: dict[str, dict[str, Any]] = {
    path: item
    for contract in _CONTRACTS.values()
    for path, item in contract["paths"].items()
}
_URI_BY_PATH = {
    path: uri for uri, contract in _CONTRACTS.items() for path in contract["paths"]
}


class HttpResponse(Protocol):
    """What the contract check reads from a test client response."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def json(self) -> Any: ...


def resolve(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Follow ``$ref`` pointers until a concrete object is reached.

    Args:
        node: Object taken from the operation of ``path``.
        path: Path template whose contract file the pointers are relative to.
    """
    resolver = _REGISTRY.resolver(_URI_BY_PATH[path])
    while "$ref" in node:
        resolved = resolver.lookup(node["$ref"])
        node, resolver = resolved.contents, resolved.resolver
    return node


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
    content = resolve(declared[status], path=path).get("content", {})
    media_type = response.headers["content-type"].split(";")[0]
    assert media_type in content, f"{status} is not declared as {media_type}"
    schema = content[media_type]["schema"]
    pointer = schema["$ref"] if "$ref" in schema else None
    assert pointer is not None, "contract bodies are named components"
    validator = Draft202012Validator(
        {"$ref": f"{_URI_BY_PATH[path]}{pointer}"},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    validator.validate(response.json())
    assert response.headers["x-request-id"]
