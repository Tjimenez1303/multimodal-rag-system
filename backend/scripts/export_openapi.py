"""Write the API's OpenAPI description, the input of the frontend's generated client.

The application is built with every router and no readiness checks, as the contract
tests build it, so no setting or external service is needed.

Usage:
    uv run --directory backend python scripts/export_openapi.py ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from multimodal_rag.adapters.http.app import create_app
from multimodal_rag.adapters.http.routes_documents import documents_router
from multimodal_rag.adapters.http.routes_ingestion import ingestion_router
from multimodal_rag.adapters.http.routes_questions import questions_router


def export_openapi(destination: Path) -> None:
    """Write the OpenAPI description of the API as indented JSON.

    Args:
        destination: File to write, replaced when it exists.
    """
    app = create_app(
        readiness_checks={},
        routers=(ingestion_router, documents_router, questions_router),
    )
    destination.write_text(json.dumps(app.openapi(), indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: export_openapi.py <destination.json>")
    export_openapi(Path(sys.argv[1]))
