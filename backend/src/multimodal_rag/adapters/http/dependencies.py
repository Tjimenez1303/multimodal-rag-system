"""FastAPI dependencies that hand use cases to the routes.

The composition root builds the use cases once and yields them as lifespan state, which
Starlette copies into every request. Routes declare them with ``Annotated`` aliases, and
tests replace the providers through ``app.dependency_overrides``.
"""

from typing import Annotated, TypedDict

from fastapi import Depends, Request

from multimodal_rag.adapters.http.request_context import request_id_of
from multimodal_rag.ingestion.use_cases.intake import GetJob, SubmitDocument
from multimodal_rag.ingestion.use_cases.library import (
    GetElementImage,
    ListDocumentElements,
)


class IngestionState(TypedDict):
    """Lifespan state that serves the ingestion and document routes.

    Attributes:
        submit_document: Use case behind the upload route.
        get_job: Use case behind the job status route.
        list_document_elements: Use case behind the elements route.
        get_element_image: Use case behind the image route.
    """

    submit_document: SubmitDocument
    get_job: GetJob
    list_document_elements: ListDocumentElements
    get_element_image: GetElementImage


def provide_submit_document(request: Request) -> SubmitDocument:
    """Return the upload use case built at startup.

    Args:
        request: Request being handled.

    Returns:
        The shared ``SubmitDocument`` instance.
    """
    use_case: SubmitDocument = request.state.submit_document
    return use_case


def provide_get_job(request: Request) -> GetJob:
    """Return the job status use case built at startup.

    Args:
        request: Request being handled.

    Returns:
        The shared ``GetJob`` instance.
    """
    use_case: GetJob = request.state.get_job
    return use_case


def provide_list_document_elements(request: Request) -> ListDocumentElements:
    """Return the elements use case built at startup.

    Args:
        request: Request being handled.

    Returns:
        The shared ``ListDocumentElements`` instance.
    """
    use_case: ListDocumentElements = request.state.list_document_elements
    return use_case


def provide_get_element_image(request: Request) -> GetElementImage:
    """Return the image use case built at startup.

    Args:
        request: Request being handled.

    Returns:
        The shared ``GetElementImage`` instance.
    """
    use_case: GetElementImage = request.state.get_element_image
    return use_case


def provide_request_id(request: Request) -> str:
    """Return the correlation id of the request.

    Args:
        request: Request being handled.

    Returns:
        The id the request context assigned, the same one problem details carry.
    """
    return request_id_of(request)


SubmitDocumentDep = Annotated[SubmitDocument, Depends(provide_submit_document)]
GetJobDep = Annotated[GetJob, Depends(provide_get_job)]
RequestIdDep = Annotated[str, Depends(provide_request_id)]
ListDocumentElementsDep = Annotated[
    ListDocumentElements, Depends(provide_list_document_elements)
]
GetElementImageDep = Annotated[GetElementImage, Depends(provide_get_element_image)]
