"""Routes that expose what ingestion captured from each document."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response

from multimodal_rag.adapters.http.dependencies import (
    GetDocumentDep,
    GetElementImageDep,
    GetPageImageDep,
    ListDocumentElementsDep,
    ListDocumentsDep,
)
from multimodal_rag.adapters.http.problems import problem_responses
from multimodal_rag.adapters.http.routes_ingestion import API_PREFIX
from multimodal_rag.adapters.http.schemas import (
    DocumentBody,
    DocumentPageBody,
    ElementBody,
    ElementPageBody,
)
from multimodal_rag.ingestion.domain import ElementKind

PNG_MEDIA_TYPE = "image/png"
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
_PNG_RESPONSE: dict[str, Any] = {
    "description": "PNG image",
    "content": {PNG_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
}

documents_router = APIRouter(prefix=API_PREFIX, tags=["documents"])


@documents_router.get(
    "/documents",
    operation_id="listDocuments",
    description="Known documents with their latest job status, newest first.",
    responses=problem_responses(400),
)
async def list_documents(
    list_page: ListDocumentsDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> DocumentPageBody:
    """Return one page of the document library.

    Args:
        list_page: Library use case.
        limit: Largest number of documents to return.
        cursor: Cursor returned by the previous page.

    Returns:
        The documents with their latest jobs and the cursor of the next page.
    """
    result = await list_page(limit=limit, cursor=cursor)
    return DocumentPageBody(
        items=[DocumentBody.from_view(view) for view in result.items],
        next_cursor=result.next_cursor,
    )


@documents_router.get(
    "/documents/{document_id}",
    operation_id="getDocument",
    description="A document and its latest job.",
    responses=problem_responses(400, 404),
)
async def get_document(document_id: uuid.UUID, get_one: GetDocumentDep) -> DocumentBody:
    """Return a document with its latest job.

    Args:
        document_id: Id of the document.
        get_one: Document use case.

    Returns:
        The document and its newest job.
    """
    return DocumentBody.from_view(await get_one(document_id))


@documents_router.get(
    "/documents/{document_id}/elements",
    operation_id="listDocumentElements",
    description="Captured elements of a completed document, in reading order.",
    responses=problem_responses(400, 404, 409),
)
async def list_document_elements(
    document_id: uuid.UUID,
    list_elements: ListDocumentElementsDep,
    request: Request,
    page: Annotated[int | None, Query(ge=1)] = None,
    kind: ElementKind | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> ElementPageBody:
    """Return one page of the captured elements of a document.

    Args:
        document_id: Document whose elements are listed.
        list_elements: Elements use case.
        request: Request being handled, used to build image URLs.
        page: Only elements of this 1-based page, when set.
        kind: Only elements of this kind, when set.
        limit: Largest number of elements to return.
        cursor: Cursor returned by the previous page.

    Returns:
        The elements with their relationships and the cursor of the next page.
    """
    result = await list_elements(
        document_id, page_number=page, kind=kind, limit=limit, cursor=cursor
    )
    items = [
        ElementBody.from_view(
            view,
            image_url=request.url_for(
                "get_document_image",
                document_id=str(document_id),
                element_id=str(view.element.id),
            ).path
            if view.element.image_key
            else None,
        )
        for view in result.items
    ]
    return ElementPageBody(items=items, next_cursor=result.next_cursor)


@documents_router.get(
    "/documents/{document_id}/images/{element_id}",
    operation_id="getDocumentImage",
    description="Stored crop of an image element.",
    response_class=Response,
    responses={200: _PNG_RESPONSE, **problem_responses(400, 404)},
)
async def get_document_image(
    document_id: uuid.UUID, element_id: uuid.UUID, get_image: GetElementImageDep
) -> Response:
    """Return the PNG crop of an image element.

    Args:
        document_id: Document the image belongs to.
        element_id: Id of the image element.
        get_image: Image use case.

    Returns:
        The PNG bytes.
    """
    return Response(
        content=await get_image(document_id, element_id), media_type=PNG_MEDIA_TYPE
    )


@documents_router.get(
    "/documents/{document_id}/pages/{page_number}/image",
    operation_id="getDocumentPageImage",
    description=(
        "PNG of a whole page at 144 dpi, stored when the document was ingested. "
        "Available once the document's latest job has completed."
    ),
    response_class=Response,
    responses={200: _PNG_RESPONSE, **problem_responses(400, 404, 409)},
)
async def get_document_page_image(
    document_id: uuid.UUID,
    page_number: Annotated[int, Path(ge=1)],
    get_page: GetPageImageDep,
) -> Response:
    """Return the rendered image of a page of a completed document.

    Args:
        document_id: Document the page belongs to.
        page_number: 1-based page number.
        get_page: Page image use case.

    Returns:
        The PNG bytes.
    """
    return Response(
        content=await get_page(document_id, page_number), media_type=PNG_MEDIA_TYPE
    )
